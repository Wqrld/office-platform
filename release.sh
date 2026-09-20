#!/usr/bin/env bash
# Publish one version of the platform: the config artifact and the four charts, under one
# number.
#
#   ./release.sh 2.0.0
#
# That is all this does. A cluster moves to the version by editing the chart tag in its
# own cluster.yaml (examples/cluster.yaml); rolling back is editing it back. Nothing here
# points anything anywhere, and there is no moving tag: the old `:latest` existed only
# because the version pointer lived inside the tree it pointed at, and it no longer does.
#
# One number across everything, because the control plane pins the platform charts and the
# config artifact at its own version — a mixed set is not a state anyone should have to
# reason about. The charts' Chart.yaml files are rewritten to it; commit that afterwards.
# The revision recorded in the artifacts is read BEFORE that rewrite, so a version's
# recorded commit is the one it was built from, not the one that bumps the number.
#
# A version that already exists is never re-pushed, so published versions are immutable
# and a rollback cannot rewrite the thing being rolled back to. Everything is packaged
# before anything is pushed, and the control plane — the one artifact a cluster pins — goes
# last: a push that fails halfway burns the number, but leaves nothing a cluster can use.
set -euo pipefail

REGISTRY="harbor.mijnbureau.haaijer.dev/office"
CREDS_FILE="${HARBOR_ROBOT_FILE:-/root/.harbor-robot}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHARTS=(platform-deps platform-app platform-tenants control-plane)
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 <major.minor.patch>" >&2
  exit 2
fi

[[ -r "$CREDS_FILE" ]] || { echo "no harbor creds at $CREDS_FILE" >&2; exit 1; }
USER="$(head -1 "$CREDS_FILE")"; PASS="$(sed -n 2p "$CREDS_FILE")"

# Untracked files count: `flux push` ships them, and an artifact stamped with a commit
# must be that commit.
SHA="$(git -C "$HERE" rev-parse --short HEAD)"
if [[ -n "$(git -C "$HERE" status --porcelain)" ]]; then
  echo "working tree is dirty — commit or stash first, so $VERSION is traceable to $SHA" >&2
  exit 1
fi

tags() {   # every tag of one repository under the registry
  curl -sS -u "$USER:$PASS" "https://${REGISTRY%%/*}/v2/${REGISTRY#*/}/$1/tags/list" \
    | python3 -c 'import sys,json;print(" ".join(json.load(sys.stdin).get("tags") or []))'
}
for repo in config "${CHARTS[@]/#/charts/}"; do
  if [[ " $(tags "$repo") " == *" $VERSION "* ]]; then
    echo "$repo:$VERSION is already published — versions are immutable, pick the next one" >&2
    exit 1
  fi
done

for c in "${CHARTS[@]}"; do
  sed -i "s/^version: .*/version: $VERSION/; s/^appVersion: .*/appVersion: \"$VERSION\"/" "$HERE/charts/$c/Chart.yaml"
  helm package "$HERE/charts/$c" --destination "$WORK" >/dev/null
done

# `.sourceignore` is what source-controller honours for git and bucket sources; `flux push`
# reads nothing but --ignore-paths, so the same file is handed to it here. Without this
# the artifact carried tests/, the charts and a local build — nothing the cluster reads.
IGNORE="$(grep -Ev '^\s*(#|$)' "$HERE/.sourceignore" | paste -sd,)"
echo "config:$VERSION"
flux push artifact "oci://${REGISTRY}/config:$VERSION" \
  --path="$HERE" --source=office-platform --revision="${VERSION}@sha1:${SHA}" \
  --ignore-paths=".git/,$IGNORE" --creds="$USER:$PASS"

echo "$PASS" | helm registry login "${REGISTRY%%/*}" --username "$USER" --password-stdin
for c in "${CHARTS[@]}"; do
  echo "charts/$c:$VERSION"
  helm push "$WORK/$c-$VERSION.tgz" "oci://$REGISTRY/charts"
done

echo
echo "published $VERSION. commit the Chart.yaml bumps, then run it on a cluster by setting"
echo "  ref: {tag: \"$VERSION\"}"
echo "in its cluster.yaml; it lands with:"
echo "  flux -n flux-system reconcile source oci flux-system && flux get hr -n flux-system"
