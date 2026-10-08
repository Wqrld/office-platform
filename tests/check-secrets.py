#!/usr/bin/env python3
"""Do the `postRenderers` envFrom patches still hit exactly the workloads they should?

    ./tests/check-secrets.py [app ...]      default: every app with an envFrom patch

For an upstream chart with no `envFrom` of its own, a Flux patch adds it, and the patch's
name selector is the security boundary (`meet-backend.*` must never reach `meet-frontend`).
Against the release as helm-controller applies it: every patch matches some workload, and
every workload's first container gets exactly the envFrom of the patches that target it.
See `AGENTS.md` (Checks).
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402


def check(app: str, srcs: dict) -> list[str]:
    problems: list[str] = []
    docs = render.apps("medium", [app])
    for rel in (d for d in docs if d.get("kind") == "HelmRelease"):
        patches = [p for r in rel["spec"].get("postRenderers", []) for p in r["kustomize"].get("patches", [])
                   if "/envFrom" in p["patch"]]
        if not patches:
            continue
        hit = [0] * len(patches)
        for d, pod, _ in render.pod_specs(render.release(rel, docs, srcs)):
            got, want = pod["containers"][0].get("envFrom", []), []
            for i, p in enumerate(patches):
                t = p["target"]
                if re.fullmatch(t["kind"], d["kind"]) and re.fullmatch(t["name"], d["metadata"]["name"]):
                    hit[i] += 1
                    want += [op["value"] for op in render.load(p["patch"]) if op["path"].endswith("/envFrom")][0]
            names = ",".join(list(e.values())[0]["name"] for e in got) or "(none)"
            print(f"{'ok  ' if got == want else 'FAIL'} {d['kind']:<11} {d['metadata']['name']:<48} {names}")
            if got != want:
                problems.append(f"{app}: {d['kind']}/{d['metadata']['name']} gets envFrom {names}, "
                                f"the patches targeting it give {want}")
        problems += [f"{app}: patch {p['target']} matches no workload — a silent no-op"
                     for p, n in zip(patches, hit, strict=True) if not n]
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apps", nargs="*", help="default: every app with an envFrom patch")
    args = ap.parse_args()
    apps = args.apps or [a for a in render.APPS
                         if "/envFrom" in (render.ROOT / "apps" / a / "release.yaml").read_text()]
    srcs = render.sources()
    problems = [p for a in apps for p in check(a, srcs)]
    return render.report(problems, "every envFrom patch hits exactly the workloads it targets",
                         "envFrom problem(s)")


if __name__ == "__main__":
    sys.exit(main())
