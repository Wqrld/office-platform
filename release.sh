#!/usr/bin/env bash
# Release one version of the platform: a commit that sets it everywhere, tagged `v<version>`.
#
#   ./release.sh 2.3.0 && git push origin HEAD v2.3.0
#
# A cluster reads the config and the four charts from that tag (docs/adr/0114), so this
# publishes nothing itself: pushing the tag is the release, and the release workflow turns
# it into a GitHub release. A cluster moves to the version by editing the tag in its own
# cluster.yaml (examples/cluster.yaml); rolling back is editing it back.
#
# One number across everything, because the control plane pins the platform source at its
# own version — a mixed set is not a state anyone should have to reason about. A tag that
# exists is never reused, so a rollback cannot rewrite the thing being rolled back to; the
# repository's tag protection is what keeps a pushed one from moving.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 <major.minor.patch>" >&2
  exit 2
fi
TAG="v$VERSION"
cd "$HERE"

[[ -z "$(git status --porcelain)" ]] || { echo "working tree is dirty — commit or stash first" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || [[ -n "$(git ls-remote --tags origin "$TAG")" ]]; then
  echo "$TAG exists — versions are immutable, pick the next one" >&2
  exit 1
fi
grep -q '^## Unreleased$' CHANGELOG.md || { echo "CHANGELOG.md has no '## Unreleased' section" >&2; exit 1; }

# perl rather than `sed -i`, whose in-place flag and `\n` differ between GNU and BSD/macOS.
TODAY="$(date +%F)"
export VERSION TAG TODAY
perl -pi -e 's/^version: .*/version: $ENV{VERSION}/; s/^appVersion: .*/appVersion: "$ENV{VERSION}"/' charts/*/Chart.yaml
perl -pi -e 's/ref: \{tag: v[0-9.]*\}/ref: {tag: $ENV{TAG}}/' examples/cluster.yaml
perl -pi -e 's/^## Unreleased$/## Unreleased\n\n## $ENV{VERSION} — $ENV{TODAY}/' CHANGELOG.md

git commit -qam "🔖 (release) $VERSION"
git tag -a "$TAG" -m "$VERSION"
echo "tagged $TAG. publish it with:  git push origin HEAD $TAG"
