#!/usr/bin/env bash
# Assert that the post-render patches in release.yaml attach the secrets to every backend
# workload and to none of the frontend. Run it after bumping the Drive chart.
#
#   ./check-secrets.sh [path-to-drive-checkout]
#
# With no argument it clones the tag that `charts/control-plane/templates/sources.yaml` pins. It reads the
# patches out of release.yaml rather than restating them, so this cannot drift from what is
# actually deployed.
#
# Why this exists: kustomize matches `name` as a FULL-STRING regex, so `^drive-backend`
# silently selects one object instead of ten, and the failure only shows up as a
# crash-looping pod at deploy time.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

SRC="${1:-}"
if [[ -z "$SRC" ]]; then
  TAG="$(python3 -c "
import re,sys
s=open('$HERE/../../charts/control-plane/templates/sources.yaml').read()
i=s.index('suitenumerique-drive')
print(re.search(r'ref: \{tag: (\S+)\}', s[i:]).group(1))")"
  echo "cloning drive at $TAG"
  git clone --quiet --depth 1 --branch "$TAG" https://github.com/suitenumerique/drive "$WORK/src"
  SRC="$WORK/src"
fi

helm template drive "$SRC/src/helm/drive" -n office-drive \
  -f <(python3 -c "
import yaml,sys
d=yaml.safe_load(open('$HERE/release.yaml'))
yaml.safe_dump(d['spec']['values'], sys.stdout)") > "$WORK/all.yaml"

python3 -c "
import yaml
d=yaml.safe_load(open('$HERE/release.yaml'))
yaml.safe_dump({'resources':['all.yaml'],
                'patches':d['spec']['postRenderers'][0]['kustomize']['patches']},
               open('$WORK/kustomization.yaml','w'))"

kubectl kustomize "$WORK" > "$WORK/rendered.yaml"

python3 - "$WORK/rendered.yaml" "$HERE/release.yaml" <<'PY'
import sys, yaml

rendered, release = sys.argv[1], sys.argv[2]
patch = yaml.safe_load(
    yaml.safe_load(open(release))["spec"]["postRenderers"][0]["kustomize"]["patches"][0]["patch"]
)
want = sorted(list(e.values())[0]["name"] for e in patch[0]["value"])

fail = False
for d in yaml.safe_load_all(open(rendered)):
    if not d:
        continue
    spec = d.get("spec", {})
    tmpl = spec.get("template") or spec.get("jobTemplate", {}).get("spec", {}).get("template")
    if not tmpl:
        continue
    name = d["metadata"]["name"]
    got = sorted(list(e.values())[0]["name"] for e in tmpl["spec"]["containers"][0].get("envFrom", []))
    # Backend workloads need every secret; the frontend must hold none of them — it renders
    # for the browser and has no business with the database password or the client secret.
    expect = want if name.startswith("drive-backend") else []
    ok = got == expect
    fail |= not ok
    print(f"{'ok  ' if ok else 'FAIL'} {d['kind']:<11} {name:<52} {','.join(got) or '(none)'}")

print("\nFAIL" if fail else "\nOK")
sys.exit(1 if fail else 0)
PY
