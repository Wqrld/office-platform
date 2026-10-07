#!/usr/bin/env bash
# Is what the charts render, and what Flux would apply, actually valid for the API server?
#
#   ./tests/kubeconform.sh [dir ...]    default: tests/golden, plus a fresh build of every cluster
#
# Two things this does that a bare kubeconform run does not:
#
# 1. It resolves ${BASE_DOMAIN} in the goldens first. Chart cases carry the Flux
#    substitution literal on purpose, because that is what the HelmRelease carries — but
#    `${...}` is not a legal hostname, so validating before substitution reports failures
#    for the one thing that is definitely correct. A build is already substituted.
#
# 2. It uses the CRD catalog. Most of what this repo emits is a CRD (HTTPRoute,
#    ExternalSecret, Kustomization, GarageBucket…). With `default` schemas alone,
#    kubeconform silently SKIPS all of them and reports a confident pass having validated
#    only the Services and Deployments — a green tick over almost nothing.
#
# `-strict` rejects unknown fields, which is the half that catches a typo'd key in a CR.
# `-ignore-missing-schemas` is needed for the one kind no schema set carries, so a kind
# that loses its schema — a catalog rename, an apiVersion bump the catalog lacks — would
# silently move from "validated" to "skipped". The catalog is pinned to a commit and any
# skipped kind other than the expected one fails the check.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBE_VERSION="$(cd "$HERE/tests" && python3 -c 'import render; print(render.KUBE_VERSION)')"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if (( $# )); then
  DIRS=("$@")
else
  echo "== building every cluster"
  "$HERE/tests/build.py" "$WORK/built" >/dev/null
  DIRS=("$HERE/tests/golden" "$WORK/built")
fi

# Only the substitution that reaches chart output; mirrors a cluster's cluster-vars.
BASE_DOMAIN="${BASE_DOMAIN:-example.org}"
i=0
for d in "${DIRS[@]}"; do
  for f in "$d"/*.yaml "$d"/*/*.yaml; do
    [[ -s "$f" ]] || continue          # minimal-deps renders empty on purpose
    i=$((i + 1))                       # a counter in the redirection itself would tick in the child
    sed "s/\${BASE_DOMAIN}/$BASE_DOMAIN/g" "$f" > "$WORK/$i-$(basename "$f")"
  done
done

CATALOG_REV=ad3b08c5045129d7bb1eeffd8e61719b2c8dd1e2   # datreeio/CRDs-catalog, 2026-09-20
CATALOG="https://raw.githubusercontent.com/datreeio/CRDs-catalog/$CATALOG_REV/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
# Kinds the catalog does not carry, vendored from the cluster's own CRDs — tests/schemas.
LOCAL="$HERE/tests/schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"

shopt -s nullglob
files=("$WORK"/*.yaml)
(( ${#files[@]} )) || { echo "kubeconform: nothing to validate in ${DIRS[*]}" >&2; exit 1; }

kubeconform \
  -kubernetes-version "$KUBE_VERSION" \
  -strict \
  -summary \
  -verbose \
  -ignore-missing-schemas \
  -schema-location default \
  -schema-location "$CATALOG" \
  -schema-location "$LOCAL" \
  "${files[@]}" | tee "$WORK/out.txt"

echo
echo "== kinds with no schema (validated by nothing above)"
# CustomResourceDefinition is expected: the standalone schema set carries every
# sub-definition of a CRD and not the object itself. The CRDs here are vendored upstream
# files anyway (platform/identity/vendor/ records where each came from).
skipped="$(grep " skipped$" "$WORK/out.txt" | awk '{print $(NF-1)}' | sort -u | grep -vx CustomResourceDefinition || true)"
if [[ -n "$skipped" ]]; then
  echo "$skipped" | sed 's/^/  /'
  echo "FAIL — these kinds were validated by nothing; pin a schema in tests/schemas or bump CATALOG_REV" >&2
  exit 1
fi
echo "   none (CustomResourceDefinition excepted)"
