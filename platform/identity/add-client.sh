#!/usr/bin/env bash
# Create one client from realm.yaml in a realm that is ALREADY imported.
#
#   ./add-client.sh drive
#
# The realm import is import-once (see README.md), so adding a client to `realm.yaml` does
# not create it. This takes the client straight out of that file — so the live realm and
# git say the same thing — resolves ${BASE_DOMAIN} and the $${CLIENT_SECRET_*} placeholder
# from the cluster, and POSTs it.
#
# Idempotent: a client that already exists is reported and left alone. It never PUTs, so it
# cannot silently rewrite a client someone changed by hand.
set -euo pipefail

CLIENT="${1:-}"
[[ -n "$CLIENT" ]] || { echo "usage: $0 <clientId>" >&2; exit 2; }

NS=office-identity
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BASE_DOMAIN="$(kubectl -n flux-system get cm cluster-vars -o jsonpath='{.data.BASE_DOMAIN}')"
KC="https://id.${BASE_DOMAIN}"

ADMIN_PW="$(kubectl -n "$NS" get secret keycloak-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d)"
SECRET="$(kubectl -n "$NS" get secret "oidc-client-${CLIENT}" -o jsonpath='{.data.secret}' | base64 -d)"

TOKEN="$(curl -sS -d client_id=admin-cli -d username=admin --data-urlencode "password=${ADMIN_PW}" \
  -d grant_type=password "${KC}/realms/master/protocol/openid-connect/token" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"

BODY="$(CLIENT="$CLIENT" BASE_DOMAIN="$BASE_DOMAIN" SECRET="$SECRET" python3 - "$HERE/realm.yaml" <<'PY'
import json, os, sys, yaml

want, domain, secret = os.environ["CLIENT"], os.environ["BASE_DOMAIN"], os.environ["SECRET"]
# realm.yaml is a multi-document file; the import is the KeycloakRealmImport.
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d]
realm = next(d for d in docs if d["kind"] == "KeycloakRealmImport")["spec"]["realm"]
client = next(c for c in realm["clients"] if c["clientId"] == want)

def resolve(v):
    if isinstance(v, str):
        # $${NAME} is Flux-escaped Keycloak syntax; ${BASE_DOMAIN} is Flux's own.
        return v.replace("$${CLIENT_SECRET_%s}" % want.upper(), secret) \
                .replace("${BASE_DOMAIN}", domain)
    if isinstance(v, list):
        return [resolve(x) for x in v]
    if isinstance(v, dict):
        return {k: resolve(x) for k, x in v.items()}
    return v

client = resolve(client)
assert "${" not in json.dumps(client), "an unresolved placeholder is left in the client"
print(json.dumps(client))
PY
)"

EXISTING="$(curl -sS -H "Authorization: Bearer $TOKEN" \
  "${KC}/admin/realms/office/clients?clientId=${CLIENT}" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')"
if [[ "$EXISTING" != "0" ]]; then
  echo "client '${CLIENT}' already exists in realm office — not touching it"
  exit 0
fi

curl -sS --fail-with-body -X POST "${KC}/admin/realms/office/clients" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$BODY"

echo "created '${CLIENT}'. Confirm the secret matches what the app will read:"
echo "  curl -sS -H \"Authorization: Bearer \$TOKEN\" \\"
echo "    '${KC}/admin/realms/office/clients?clientId=${CLIENT}' | python3 -m json.tool | grep secret"
