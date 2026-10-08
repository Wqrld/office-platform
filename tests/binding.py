#!/usr/bin/env python3
"""Does our surround still attach to what the upstream charts create?

    ./tests/binding.py [app ...]        default: every app under apps/

Renders each app's upstream release and its surround together, at the pinned versions and
as helm-controller applies them, and asserts: every HTTPRoute backendRef names a Service
that exists, on a port it exposes; the upstream release emits no Ingress and none of the
kinds the surround owns (PDB, ServiceMonitor, HPA, NetworkPolicy). The only check that
notices an upstream rename. See `AGENTS.md` (Checks).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

# Two of these selecting the same pods is the failure: two PDBs on one workload hang a drain.
SURROUND_OWNED = {"PodDisruptionBudget", "ServiceMonitor", "HorizontalPodAutoscaler", "NetworkPolicy"}


def check_app(app: str, srcs: dict) -> list[str]:
    problems: list[str] = []
    docs = render.apps("medium", [app])
    upstream: list[dict] = []
    surround: list[dict] = []
    plain = [d for d in docs if d.get("kind") not in {"HelmRelease", "Kustomization"}]
    for rel, out, err in render.releases(docs, srcs):
        if err:
            problems.append(f"{app}/{rel['metadata']['name']}: {err}")
        (surround if render.local_chart(rel) else upstream).extend(out)

    services: dict[str, set[int]] = {}
    for d in upstream + surround + plain:
        if d.get("kind") == "Service":
            ports = {p["port"] for p in d["spec"].get("ports", []) if "port" in p}
            services.setdefault(d["metadata"]["name"], set()).update(ports)

    for d in surround:
        if d.get("kind") != "HTTPRoute":
            continue
        route = d["metadata"]["name"]
        for rule in d["spec"].get("rules", []):
            for b in rule.get("backendRefs", []):
                n, p = b["name"], b.get("port")
                if n not in services:
                    problems.append(f"{app}: HTTPRoute/{route} routes to Service {n!r}, which no release creates")
                elif p is not None and p not in services[n]:
                    have = sorted(services[n]) or "no ports at all"
                    problems.append(f"{app}: HTTPRoute/{route} routes to {n}:{p}, but that Service exposes {have}")

    for d in upstream:
        k = d.get("kind")
        if k in SURROUND_OWNED:
            problems.append(f"{app}: the upstream release emits {k}/{d['metadata']['name']} — the surround "
                            f"owns that kind, and two of them selecting the same pods is a drain that hangs")
        if k == "Ingress":
            problems.append(f"{app}: the upstream release emits Ingress/{d['metadata']['name']} — "
                            f"routing is Gateway API here, and a live Ingress is a second way in")

    print(f"   {app:12} {len(upstream)} upstream + {len(surround)} surround + {len(plain)} plain objects, "
          f"{len(services)} services")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apps", nargs="*", help="default: every app under apps/")
    args = ap.parse_args()
    srcs = render.sources()
    problems: list[str] = []
    print("== rendering upstream releases at their pinned versions")
    for app in args.apps or [a for a in render.APPS if (render.ROOT / "apps" / a / "release.yaml").exists()]:
        problems += check_app(app, srcs)
    return render.report(problems, "every route resolves, and no upstream release emits a surround-owned kind",
                         "binding problem(s)")


if __name__ == "__main__":
    sys.exit(main())
