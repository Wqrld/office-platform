#!/usr/bin/env bash
# Check whether a newer Keycloak operator release exists and, if so, re-download all five
# vendored files AND bump the version comment in this directory's kustomization.yaml, in
# one pass. The two must never move separately — a version bump with stale files would be
# a repository that lies about what it runs (updatecli/README.md explains why this pin is
# not an updatecli text-substitution target).
#
#   ./update.sh          # no-op and exit 0 if already current
#
# Idempotent and side-effect-free when nothing changed, so it is safe to run from CI on a
# schedule (.github/workflows/upstream-updates.yaml) as well as by hand.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="keycloak/keycloak-k8s-resources"
FILES=(
  keycloakoidcclients.k8s.keycloak.org-v1.yml
  keycloakrealmimports.k8s.keycloak.org-v1.yml
  keycloaks.k8s.keycloak.org-v1.yml
  keycloaksamlclients.k8s.keycloak.org-v1.yml
  kubernetes.yml
)

CURRENT="$(python3 -c "
import re
s = open('$HERE/kustomization.yaml').read()
print(re.search(r'tree/([0-9]+\.[0-9]+\.[0-9]+)/kubernetes', s).group(1))
")"

# Newest stable tag, same rule as updatecli.d/helm-charts.yaml: no ceiling, a human reads
# the diff. Pre-releases (anything with a '-') are excluded.
LATEST="$(python3 -c "
import json, urllib.request

req = urllib.request.Request(
    'https://api.github.com/repos/$REPO/tags?per_page=100',
    headers={'Accept': 'application/vnd.github+json'},
)
tags = json.load(urllib.request.urlopen(req))
versions = []
for t in tags:
    name = t['name']
    parts = name.split('.')
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        versions.append(tuple(int(p) for p in parts))
print('.'.join(str(p) for p in max(versions)))
")"

if [[ "$CURRENT" == "$LATEST" ]]; then
  echo "keycloak operator: up to date at $CURRENT"
  exit 0
fi

echo "keycloak operator: $CURRENT -> $LATEST"

# Everything is fetched before anything in the tree is touched, so a download that fails
# halfway leaves the vendored set at one version, not two.
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
for f in "${FILES[@]}"; do
  curl -fsSL "https://raw.githubusercontent.com/$REPO/$LATEST/kubernetes/$f" -o "$STAGE/$f"
done
mv "$STAGE"/* "$HERE/"

sed -i "s/${CURRENT//./\\.}/$LATEST/g" "$HERE/kustomization.yaml"   # the one place the pin is written

echo "re-downloaded ${#FILES[@]} files and bumped the pin to $LATEST — diff before committing"
