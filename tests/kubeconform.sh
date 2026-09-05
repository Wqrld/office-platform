#!/usr/bin/env bash
# Is what Flux would apply actually valid for the API server?
#
#   ./tests/kubeconform.sh [dir]     default: build every cluster first, into a temp dir
#
# The charts repo validates what the charts render. This validates the other half — the
# HelmReleases, Kustomizations, operator CRs and plain manifests this repo writes by hand,
# after kustomize has merged the size profile over them. A size-profile patch that targets
# a path the chart does not have is a silent no-op; one that produces a malformed object is
# caught here and nowhere else, because nothing in this repo renders those values.
#
# `-strict` rejects unknown fields, which is the half that catches a typo'd key in a CR.
# Kinds still skipped are printed at the end rather than hidden: an unvalidated kind is a
# gap, not a pass.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBE_VERSION="${KUBE_VERSION:-1.34.2}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [[ -n "${1:-}" ]]; then
  DIR="$1"
else
  echo "== building (no directory given)"
  "$HERE/tests/build.sh" "$WORK/built" >/dev/null
  DIR="$WORK/built"
fi

CATALOG="https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
# Kinds the catalog does not carry, vendored from the cluster's own CRDs — tests/schemas.
LOCAL="$HERE/tests/schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"

shopt -s nullglob
files=("$DIR"/*/*.yaml)
(( ${#files[@]} )) || { echo "kubeconform: nothing to validate in $DIR" >&2; exit 1; }

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
  # line shape: "<file> - <name> <Kind> skipped"
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
