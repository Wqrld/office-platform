#!/usr/bin/env bash
# Release or roll back the cluster config.
#
#   ./release.sh 1.1.0     ship a new version
#   ./release.sh 1.0.0     roll back to one already in the registry
#
# Both are the same gesture: point `clusters/prod/config-source.yaml` at a version and
# push :latest so Flux sees the new pointer. The difference is handled automatically —
# a version tag that already exists is NEVER re-pushed, so published versions stay
# immutable and rolling back cannot rewrite the thing you are rolling back to.
set -euo pipefail

REPO="harbor.mijnbureau.haaijer.dev/office/config"
CREDS_FILE="${HARBOR_ROBOT_FILE:-/root/.harbor-robot}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POINTER="$HERE/clusters/prod/config-source.yaml"

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 <major.minor.patch>" >&2
  exit 2
fi

[[ -r "$CREDS_FILE" ]] || { echo "no harbor creds at $CREDS_FILE" >&2; exit 1; }
CREDS="$(head -1 "$CREDS_FILE"):$(sed -n 2p "$CREDS_FILE")"

SHA="$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if ! git -C "$HERE" diff --quiet HEAD 2>/dev/null; then
  echo "WARNING: working tree is dirty — $VERSION will not match any commit" >&2
  SHA="${SHA}-dirty"
fi

# Does this version already exist? If so we are repointing, not publishing.
EXISTING="$(curl -sS -u "$CREDS" "https://${REPO%%/*}/v2/${REPO#*/}/tags/list" \
            | python3 -c 'import sys,json;print(" ".join(json.load(sys.stdin).get("tags") or []))')"
PUBLISH=yes
for t in $EXISTING; do [[ "$t" == "$VERSION" ]] && PUBLISH=no; done

# The pointer travels inside both tags, so set it before either push.
python3 - "$POINTER" "$VERSION" <<'PY'
import re, sys
path, version = sys.argv[1], sys.argv[2]
s = open(path).read()
new, n = re.subn(r'(ref: \{tag: ")[^"]+(")', rf'\g<1>{version}\g<2>', s)
assert n == 1, f"expected exactly one tag to rewrite, found {n}"
open(path, 'w').write(new)
PY
echo "pointer -> $VERSION"

push() {
  flux push artifact "oci://${REPO}:$1" \
    --path="$HERE" --source=office-platform --revision="${VERSION}@sha1:${SHA}" \
    --creds="$CREDS"
}

if [[ "$PUBLISH" == yes ]]; then
  echo "publishing :$VERSION"
  push "$VERSION"
else
  echo ":$VERSION already published — repointing only, not overwriting it"
fi

# :latest carries clusters/prod, which is where Flux reads the pointer from.
echo "pushing :latest"
push latest

echo
echo "done. watch it land with:"
echo "  flux -n flux-system reconcile source oci flux-system"
echo "  flux get kustomizations -A"
