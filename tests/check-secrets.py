#!/usr/bin/env python3
"""Which workloads get which Secrets, for an app whose chart has no `envFrom` of its own and
gets it from a Flux `postRenderers` patch. The NAME SELECTOR in that patch is the security
boundary (`meet-backend.*` must never reach `meet-frontend`), and a patch whose target
matches nothing is a silent no-op — so both directions are asserted against the rendered
upstream chart at its pinned version: every patch hits something, every workload's envFrom
is exactly the union of the patches that target it.

  ./tests/check-secrets.py [app…]      default: every app with an envFrom patch
"""
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402


def workloads(objects):
    for d in objects:
        spec = d.get("spec", {})
        tmpl = spec.get("template") or spec.get("jobTemplate", {}).get("spec", {}).get("template")
        if tmpl:
            yield d, tmpl["spec"]["containers"][0].get("envFrom", [])


def check(app: str, srcs: dict, variables: dict) -> bool:
    ok = True
    for rel in render.docs_in((render.ROOT / "apps" / app / "release.yaml").read_text()):
        if rel.get("kind") != "HelmRelease":
            continue
        name = rel["metadata"]["name"]
        patches = [p for r in rel["spec"].get("postRenderers", []) for p in r["kustomize"].get("patches", [])
                   if "/envFrom" in p["patch"]]
        if not patches:
            continue
        rendered = render.helm_template(render.chart_for(rel, srcs), name, rel["metadata"]["namespace"],
                                        render.substitute(rel["spec"].get("values") or {}, variables))
        with tempfile.TemporaryDirectory() as work:
            pathlib.Path(work, "all.yaml").write_text(yaml.safe_dump_all(rendered))
            pathlib.Path(work, "kustomization.yaml").write_text(yaml.safe_dump({"resources": ["all.yaml"], "patches": patches}))
            patched = render.docs_in(render.run(["kubectl", "kustomize", work]))

        hit = [0] * len(patches)
        for d, got in workloads(patched):
            want = []
            for i, p in enumerate(patches):
                t = p["target"]
                if re.fullmatch(t["kind"], d["kind"]) and re.fullmatch(t["name"], d["metadata"]["name"]):
                    hit[i] += 1
                    want += [op["value"] for op in yaml.safe_load(p["patch"]) if op["path"].endswith("/envFrom")][0]
            good = got == want
            ok &= good
            print(f"{'ok  ' if good else 'FAIL'} {d['kind']:<11} {d['metadata']['name']:<48} "
                  f"{','.join(list(e.values())[0]['name'] for e in got) or '(none)'}")
        for p, n in zip(patches, hit):
            if not n:
                ok = False
                print(f"FAIL patch {p['target']} matches no workload — a silent no-op")
    return ok


def main() -> int:
    apps = sys.argv[1:] or [a for a in render.APPS if "/envFrom" in (render.ROOT / "apps" / a / "release.yaml").read_text()]
    srcs, variables = render.sources(), render.variables()
    ok = all([check(a, srcs, variables) for a in apps])
    print("\nOK" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
