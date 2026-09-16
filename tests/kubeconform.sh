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
# Kinds still skipped are printed at the end rather than hidden: an unvalidated kind is a
# gap, not a pass.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBE_VERSION="${KUBE_VERSION:-1.34.2}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if (( $# )); then
  DIRS=("$@")
else
  echo "== building every cluster"
  "$HERE/tests/build.py" "$WORK/built" >/dev/null
  DIRS=("$HERE/tests/golden" "$WORK/built")
fi

# Only the substitution that reaches chart output; mirrors prod's cluster-vars.
BASE_DOMAIN="${BASE_DOMAIN:-haaijer.dev}"
i=0
for d in "${DIRS[@]}"; do
  for f in "$d"/*.yaml "$d"/*/*.yaml; do
    [[ -s "$f" ]] || continue          # minimal-deps renders empty on purpose
    i=$((i + 1))                       # a counter in the redirection itself would tick in the child
    sed "s/\${BASE_DOMAIN}/$BASE_DOMAIN/g" "$f" > "$WORK/$i-$(basename "$f")"
  done
done

CATALOG="https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
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
if grep -q " skipped$" "$WORK/out.txt"; then
  grep " skipped$" "$WORK/out.txt" | awk '{print $(NF-1)}' | sort | uniq -c | sed 's/^/  /'
  echo
  # CustomResourceDefinition is expected and is not worth chasing: the standalone schema set
  # carries every sub-definition of a CRD and not the object itself, so there is nothing to
  # point kubeconform at. The CRDs here are vendored upstream files anyway — we do not write
  # them, and `platform/identity/vendor/` records where each came from.
  echo "  CustomResourceDefinition has no schema upstream; anything else in this list is a gap."
else
  echo "   none"
fi
