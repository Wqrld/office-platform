#!/usr/bin/env bash
# Does values.schema.json still reject what it is there to reject?
#
#   ./tests/schema.sh
#
# Helm validates values against the schema on every render, so the POSITIVE direction is
# already covered — every case in tests/cases/ renders, therefore every case validates.
# This script exists for the other direction. A schema that has only ever seen valid input
# is indistinguishable from an absent one, and an absent one is invisible: a typo'd values
# key does not fail, it silently does nothing, which is the most common Helm failure mode
# and the reason 10-verification.md lists this as the only thing that catches it.
#
# So: every file under tests/fixtures/schema/<chart>/ must fail to render, and must fail
# with the error it names on its `# expect:` line. Failing for the wrong reason — a chart
# that errors before validation, say — is not a pass. The control plane's fixtures also
# cover its template-time refusals (an app whose dependency is off): same file, same line,
# same reason a values file must be rejected loudly.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURES="$HERE/tests/fixtures/schema"
KUBE_VERSION="${KUBE_VERSION:-1.34.2}"

fail=0

# A schema Helm cannot parse is reported per-render as a confusing values error, so check
# the files themselves first and say so plainly.
echo "== schema files"
shopt -s nullglob
schemas=("$HERE"/charts/*/values.schema.json)
(( ${#schemas[@]} )) || { echo "   none found — every chart lost its schema" >&2; exit 1; }
for s in "${schemas[@]}"; do
  chart="$(basename "$(dirname "$s")")"
  if python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$s"; then
    printf '   %-16s valid JSON\n' "$chart"
  else
    echo "   $chart: values.schema.json is not valid JSON"
    fail=1
  fi
done

# Charts that emit objects but have no schema. Named rather than skipped: the gap is the
# finding. Library charts carry no values of their own.
for chart_dir in "$HERE"/charts/*/; do
  chart="$(basename "$chart_dir")"
  [[ -f "$chart_dir/values.schema.json" ]] && continue
  if [[ "$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1])).get("type","application"))' "$chart_dir/Chart.yaml")" == "library" ]]; then
    printf '   %-16s library chart, no values of its own\n' "$chart"
  else
    echo "   $chart: NO values.schema.json — its values are unchecked"
    fail=1
  fi
done

echo
echo "== values that must be rejected"
for chart_dir in "$FIXTURES"/*/; do
  chart="$(basename "$chart_dir")"
  [[ -d "$HERE/charts/$chart" ]] || { echo "   fixtures for unknown chart $chart"; fail=1; continue; }

  # Same vendoring the renders need: a fresh checkout has no charts/*/charts/.
  if grep -q '^dependencies:' "$HERE/charts/$chart/Chart.yaml" \
     && ! compgen -G "$HERE/charts/$chart/charts/platform-lib-*.tgz" >/dev/null; then
    helm dependency build "$HERE/charts/$chart" >/dev/null
  fi

  for f in "$chart_dir"*.yaml; do
    name="$(basename "$f" .yaml)"
    expect="$(sed -n '1s/^# expect: //p' "$f")"
    if [[ -z "$expect" ]]; then
      printf '   %-20s %-38s no `# expect:` line\n' "$chart" "$name"
      fail=1
      continue
    fi

    if err="$(helm template rejected "$HERE/charts/$chart" \
                --namespace office-schema \
                --kube-version "$KUBE_VERSION" \
                --values "$f" 2>&1)"; then
      printf '   %-20s %-38s RENDERED — the schema no longer rejects it\n' "$chart" "$name"
      fail=1
    elif [[ "$err" != *"$expect"* ]]; then
      printf '   %-20s %-38s rejected, but not for its reason\n' "$chart" "$name"
      printf '      expected: %s\n' "$expect"
      printf '      got:      %s\n' "$(tr '\n' ' ' <<< "$err" | cut -c1-160)"
      fail=1
    else
      printf '   %-20s %-38s rejected: %s\n' "$chart" "$name" "$expect"
    fi
  done
done

if (( fail )); then
  echo
  echo "FAIL — the schema is not catching what it is supposed to catch."
  exit 1
fi
