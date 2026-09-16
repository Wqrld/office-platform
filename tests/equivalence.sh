#!/usr/bin/env bash
# Assert the charts still reproduce the hand-written manifests Docs ran on before the port.
#
# This is the check that made adopting the live objects a no-op — 14 objects adopted with
# identical UIDs, 0 recreated. It ran once, by hand, against files in the `config` repo
# that the same commit deleted (9e60594), so it had quietly become unrunnable: the
# comparison targets were gone and the guarantee survived only as a line in PROGRESS.md.
#
# tests/fixtures/pre-port/ freezes those files, so this runs on every PR now.
#
# See tests/fixtures/pre-port/README.md for what to do when a chart change is *meant* to
# alter one of these objects. Short version: delete the case here and say so — do not
# re-freeze the fixture from the new output.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIX="$HERE/tests/fixtures/pre-port"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail=0

echo "== docs-deps vs the hand-written datastores.yaml + secrets.yaml"
# `docs-smtp` is the one object the chart ADDS here: the pre-port cluster could not send
# mail at all, so it had nothing to compare against. Blessed by name rather than by kind —
# every other ExternalSecret in this release still has to match the frozen one, and the
# next unplanned Secret still fails.
"$HERE/tests/render.sh" docs-deps > "$WORK/deps.yaml"
"$HERE/tests/equivalence.py" --allow-extra ExternalSecret/docs-smtp "$WORK/deps.yaml" \
  "$FIX/docs-datastores.yaml" "$FIX/docs-secrets.yaml" || fail=1

echo
echo "== docs-app vs the hand-written routes.yaml"
# The NetworkPolicy is the one object the chart ADDS: the hand-written set never had one
# (adr/0103 — emitted, not enforced). Everything else it adds or drops is a failure.
"$HERE/tests/render.sh" docs-app > "$WORK/app.yaml"
"$HERE/tests/equivalence.py" --allow-extra NetworkPolicy "$WORK/app.yaml" \
  "$FIX/docs-routes.yaml" || fail=1

echo
if (( fail )); then
  echo "FAIL — the charts no longer reproduce what the cluster had before the port."
  exit 1
fi
echo "OK — both releases still reproduce the pre-port manifests"
