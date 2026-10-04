#!/usr/bin/env bash
# What does this change do to what is actually applied?
#
#   ./tests/render-diff.sh [base-ref]      default: origin/main, then main, then HEAD~1
#
# 10-verification.md calls this the highest-value practice here and the one the old repo
# lacked: it had lint, render and Conftest, but nothing that compared the result to the
# previous commit. A one-line change to a shared surround silently drops every PDB, and the
# first symptom is a node drain that never finishes.
#
# So: build every cluster at the base ref and at HEAD, and diff object by object. A chart
# bump shows exactly which of the apps move and how, before it merges rather than after.
#
# Both sides are built with THIS commit's tests/build.py, copied into the base worktree. A
# change to the build script itself would otherwise show up as a diff in every object, and
# the question this answers is what changed in the OUTPUT.
#
# It never fails the build. A render-diff has no opinion about whether a change is right —
# it makes the change visible, and the review is the judgement. What must not change without
# someone noticing is asserted by the golden files in the charts repo and by the binding
# check next to this script, both of which do fail.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
cleanup() { git -C "$HERE" worktree remove --force "$WORK/base" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

pick_base() {
  [[ -n "${1:-}" ]] && { echo "$1"; return; }
  [[ -n "${GITHUB_BASE_REF:-}" ]] && git -C "$HERE" rev-parse --verify -q "origin/$GITHUB_BASE_REF" >/dev/null \
    && { echo "origin/$GITHUB_BASE_REF"; return; }
  for ref in origin/main main HEAD~1; do
    git -C "$HERE" rev-parse --verify -q "$ref" >/dev/null && { echo "$ref"; return; }
  done
  echo ""
}

BASE_REF="$(pick_base "${1:-}")"
[[ -n "$BASE_REF" ]] || { echo "render-diff: no base to compare against (a first commit has nothing to diff)"; exit 0; }
BASE_SHA="$(git -C "$HERE" merge-base "$BASE_REF" HEAD 2>/dev/null || git -C "$HERE" rev-parse "$BASE_REF")"

echo "== base $BASE_REF ($(git -C "$HERE" log -1 --format='%h %s' "$BASE_SHA"))"
echo "== head $(git -C "$HERE" log -1 --format='%h %s' HEAD)  + uncommitted changes in the working tree"
echo

git -C "$HERE" worktree add --detach "$WORK/base" "$BASE_SHA" >/dev/null 2>&1 || {
  echo "render-diff: could not check out $BASE_SHA; nothing to compare"; exit 0; }
mkdir -p "$WORK/base/tests"
cp "$HERE"/tests/*.py "$WORK/base/tests/"

# The base is allowed to fail to build — it might predate a layer this commit adds — and
# that is reported rather than treated as this change's fault.
# Both builds at once: each writes only its own worktree and output directory.
"$WORK/base/tests/build.py" "$WORK/before" >"$WORK/base.log" 2>&1 & base_pid=$!
head_ok=1; "$HERE/tests/build.py" "$WORK/after" >"$WORK/head.log" 2>&1 || head_ok=0
if ! wait "$base_pid"; then
  echo "the base commit does not build; diffing what it managed to produce"
  sed 's/^/   /' "$WORK/base.log" | tail -5
  echo
fi
(( head_ok )) || {
  echo "FAIL — this commit does not build. tests/build.py has the detail:"; sed 's/^/   /' "$WORK/head.log"; exit 1; }

# dyff understands multi-document Kubernetes YAML: it pairs objects by name and kind rather
# than by position, so a reordered kustomize output is not a diff. `diff -u` is the fallback
# when it is not installed, which is worse — it reports the reorder as a change — but a
# render-diff nobody can run locally is not much of a practice.
if command -v dyff >/dev/null; then
  differ() { dyff between --omit-header --ignore-order-changes "$1" "$2" || true; }
else
  echo "note: dyff is not installed; falling back to a line diff, which reports reorderings"
  echo
  differ() { diff -u "$1" "$2" || true; }
fi

changed=0
mapfile -t layers < <(cd "$WORK/after" && ls */*.yaml 2>/dev/null | sort)
mapfile -t gone < <(cd "$WORK/before" 2>/dev/null && ls */*.yaml 2>/dev/null | sort)

for layer in "${gone[@]}"; do
  [[ -f "$WORK/after/$layer" ]] && continue
  echo "== $layer  REMOVED (built at the base, not here)"
  changed=1
done

for layer in "${layers[@]}"; do
  before="$WORK/before/$layer"
  if [[ ! -f "$before" ]]; then
    echo "== $layer  NEW ($(grep -c '^kind:' "$WORK/after/$layer" || true) objects, nothing to diff against)"
    changed=1
    continue
  fi
  if cmp -s "$before" "$WORK/after/$layer"; then
    printf '== %-24s unchanged\n' "$layer"
    continue
  fi
  echo "== $layer"
  differ "$before" "$WORK/after/$layer" | sed 's/^/   /'
  changed=1
done

echo
if (( changed )); then
  echo "Read the diff above as the review. Nothing here fails a build."
else
  echo "No change to what any cluster applies."
fi
