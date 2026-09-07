#!/usr/bin/env bash
# Apply realm.yaml's smtpServer to a realm that is ALREADY imported.
#
#   ./set-smtp.sh
#
# The realm import is import-once (see README.md), so adding `smtpServer` to `realm.yaml`
# does not configure mail on this cluster. This takes the block straight out of that file —
# so the live realm and git say the same thing — resolves the $${SMTP_*} placeholders from
# the cluster, and PUTs it.
#
# Unlike add-client.sh this one PUTs rather than refusing to touch what exists: there is no
# secret here that a re-run could clobber with a different value, and re-asserting what
# realm.yaml says is exactly the behaviour you want from configuration. It is safe to run
# after rotating the relay password, which is the case it will actually be used for.
#
# It reads the whole realm and puts the whole realm back. A bare {"smtpServer": …} body is
# a RealmRepresentation with every other field absent, and the fields in this realm were
# tuned deliberately — brute-force thresholds, refreshTokenMaxReuse — so a partial body is
# not worth the risk of finding out which of them reset.
set -euo pipefail

NS=office-identity
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BASE_DOMAIN="$(kubectl -n flux-system get cm cluster-vars -o jsonpath='{.data.BASE_DOMAIN}')"
KC="https://id.${BASE_DOMAIN}"

ADMIN_PW="$(kubectl -n "$NS" get secret keycloak-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d)"

# The same Secret realm.yaml's placeholders name, read the same way the import would.
kc_secret() { kubectl -n "$NS" get secret smtp-credentials -o jsonpath="{.data.$1}" | base64 -d; }
SMTP_HOST="$(kc_secret host)"
SMTP_PORT="$(kc_secret port)"
SMTP_USER="$(kc_secret username)"
SMTP_PASSWORD="$(kc_secret password)"
SMTP_STARTTLS="$(kc_secret useTLS)"
SMTP_SSL="$(kc_secret useSSL)"
SMTP_FROM="$(kc_secret from)"

TOKEN="$(curl -sS -d client_id=admin-cli -d username=admin --data-urlencode "password=${ADMIN_PW}" \
  -d grant_type=password "${KC}/realms/master/protocol/openid-connect/token" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"

CURRENT="$(curl -sS --fail-with-body -H "Authorization: Bearer $TOKEN" "${KC}/admin/realms/office")"

BODY="$(SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" SMTP_USER="$SMTP_USER" \
        SMTP_PASSWORD="$SMTP_PASSWORD" SMTP_STARTTLS="$SMTP_STARTTLS" SMTP_SSL="$SMTP_SSL" \
        SMTP_FROM="$SMTP_FROM" CURRENT="$CURRENT" \
        python3 - "$HERE/realm.yaml" <<'PY'
import json, os, re, sys, yaml

docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d]
realm = next(d for d in docs if d["kind"] == "KeycloakRealmImport")["spec"]["realm"]

def resolve(v):
    if isinstance(v, str):
        # $${NAME} is Flux-escaped Keycloak syntax; ${BASE_DOMAIN} is Flux's own and does
        # not appear in this block, but resolve() stays total so a future key is covered.
        return re.sub(r"\$\$\{(\w+)\}", lambda m: os.environ[m.group(1)], v)
    if isinstance(v, list):
        return [resolve(x) for x in v]
    if isinstance(v, dict):
        return {k: resolve(x) for k, x in v.items()}
    return v

want = {k: resolve(realm[k]) for k in ("smtpServer", "resetPasswordAllowed") if k in realm}
assert "smtpServer" in want, "realm.yaml has no smtpServer to apply"
assert "${" not in json.dumps(want), "an unresolved placeholder is left in smtpServer"

current = json.loads(os.environ["CURRENT"])
current.update(want)
print(json.dumps(current))
PY
)"

curl -sS --fail-with-body -X PUT "${KC}/admin/realms/office" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$BODY"

echo "applied smtpServer to realm office (host ${SMTP_HOST}:${SMTP_PORT}, from ${SMTP_FROM})."
echo "Keycloak masks the password on read, so confirm it by sending, not by looking:"
echo "  ${KC}/admin/master/console/#/office/realm-settings/email  ->  Test connection"
echo "Then try 'Forgot password?' on ${KC}/realms/office/account as a real realm user."
