#!/usr/bin/env bash
# Render one case, or every case, exactly the way the rest of the checks do.
#
#   ./tests/render.sh docs-app            one case to stdout
#   ./tests/render.sh --all <dir>         every case in index.yaml, one file per case
#   ./tests/render.sh --list              case names, one per line
#
# Everything else in tests/ shells out to this, so there is one definition of "what this
# case renders to" and a check can never disagree with a golden about how it was produced.
#
# Release name and namespace come from tests/cases/index.yaml, not from the filename: both
# land in the output (`app.kubernetes.io/instance`, and every `.Release.Namespace`), so a
# case that defaulted them would silently test a shape nothing deploys. Leaving --namespace
# off is worse than wrong, it is *machine-dependent* — helm falls back to the current
# kubectl context's namespace, so the same case renders differently on a laptop and in CI.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASES="$HERE/tests/cases/index.yaml"

# Pinned so rendering never consults a live cluster for its API version. CI has none, and a
# golden that changes with whatever cluster the operator happens to be pointing at is not a
# golden. Keep in step with the production cluster.
KUBE_VERSION="${KUBE_VERSION:-1.34.2}"

index() {   # name<TAB>chart<TAB>release<TAB>namespace, one line per case
  python3 -c '
import sys, yaml
for c in yaml.safe_load(open(sys.argv[1]))["cases"]:
    print("\t".join(str(c[k]) for k in ("name", "chart", "release", "namespace")))
' "$CASES"
}

# The library chart is vendored into the two application charts at package time and the
# .tgz is gitignored, so a fresh checkout has no charts/*/charts/. Build it before the
# first render rather than making every caller remember.
#
# `helm dependency build` costs ~12s, so this must fire once per chart and not once per
# case. `compgen -G` is the glob test that actually works here: a bare glob inside [[ -e ]]
# is not expanded, so the obvious guard silently never matches and every render pays 12s.
declare -A DEPS_DONE=()
deps() {
  local chart="$1"
  grep -q '^dependencies:' "$HERE/charts/$chart/Chart.yaml" || return 0
  [[ -n "${DEPS_DONE[$chart]:-}" ]] && return 0
  if ! compgen -G "$HERE/charts/$chart/charts/platform-lib-*.tgz" >/dev/null; then
    helm dependency build "$HERE/charts/$chart" >/dev/null
  fi
  DEPS_DONE[$chart]=1
  return 0
}

render() {  # render <chart> <release> <namespace> <values-name>
  deps "$1"
  helm template "$2" "$HERE/charts/$1" \
    --namespace "$3" \
    --kube-version "$KUBE_VERSION" \
    --values "$HERE/tests/cases/$4.yaml"
}

case "${1:-}" in
  --list)
    index | cut -f1
    ;;
  --all)
    out="${2:?usage: render.sh --all <outdir>}"
    mkdir -p "$out"
    while IFS=$'\t' read -r name chart release ns; do
      render "$chart" "$release" "$ns" "$name" > "$out/$name.yaml"
    done < <(index)
    ;;
  "")
    sed -n '2,6p' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
  *)
    line="$(index | awk -F'\t' -v n="$1" '$1 == n')"
    [[ -n "$line" ]] || { echo "render.sh: no case '$1' in tests/cases/index.yaml" >&2; exit 2; }
    IFS=$'\t' read -r name chart release ns <<< "$line"
    render "$chart" "$release" "$ns" "$name"
    ;;
esac
