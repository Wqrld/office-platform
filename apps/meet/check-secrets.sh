#!/usr/bin/env bash
# Assert that the post-render patches in release.yaml attach the right secrets to every
# workload: the backend's set to everything that runs backend code, the pipeline's set to
# the summary service and its workers, and nothing to the frontend. Run it after bumping
# the Meet chart. Same shape as apps/drive/check-secrets.sh, same reason: kustomize matches
# `name` as a FULL-STRING regex, and a selector that misses shows up only as a crash-looping
# pod at deploy time.
#
#   ./check-secrets.sh [path-to-meet-checkout]
#
# With no argument it clones the tag that `clusters/prod/sources.yaml` pins.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

SRC="${1:-}"
if [[ -z "$SRC" ]]; then
  TAG="$(python3 -c "
import re
s=open('$HERE/../../clusters/prod/sources.yaml').read()
i=s.index('suitenumerique-meet')
print(re.search(r'ref: \{tag: (\S+)\}', s[i:]).group(1))")"
  echo "cloning meet at $TAG"
  git clone --quiet --depth 1 --branch "$TAG" https://github.com/suitenumerique/meet "$WORK/src"
  SRC="$WORK/src"
fi

python3 -c "
import yaml
d=yaml.safe_load(open('$HERE/release.yaml'))
yaml.safe_dump(d['spec']['values'], open('$WORK/values.yaml','w'))
yaml.safe_dump({'resources':['all.yaml'],
                'patches':d['spec']['postRenderers'][0]['kustomize']['patches']},
               open('$WORK/kustomization.yaml','w'))"
helm template meet "$SRC/src/helm/meet" -n office-meet -f "$WORK/values.yaml" > "$WORK/all.yaml"
kubectl kustomize "$WORK" > "$WORK/rendered.yaml"

python3 - "$WORK/rendered.yaml" <<'PY'
import sys, yaml

BACKEND = ["meet-cache", "meet-django", "meet-oidc", "meet-postgres", "meet-s3", "meet-smtp", "meet-tokens"]
PIPELINE = ["meet-s3", "meet-summary"]

def expect(name):
    if name.startswith("meet-backend"):
        return BACKEND
    if name == "meet-summary" or name.startswith("meet-celery-") and name != "meet-celery-backend":
        return PIPELINE
    return []           # frontend, the agents, and the backend's own (idle) Celery worker

fail = False
for d in yaml.safe_load_all(open(sys.argv[1])):
    spec = (d or {}).get("spec", {})
    tmpl = spec.get("template") or spec.get("jobTemplate", {}).get("spec", {}).get("template")
    if not tmpl:
        continue
    name = d["metadata"]["name"]
    got = sorted(e["secretRef"]["name"] for e in tmpl["spec"]["containers"][0].get("envFrom", []))
    ok = got == expect(name)
    fail |= not ok
    print(f"{'ok  ' if ok else 'FAIL'} {d['kind']:<11} {name:<36} {','.join(got) or '(none)'}")

print("\nFAIL" if fail else "\nOK")
sys.exit(1 if fail else 0)
PY
