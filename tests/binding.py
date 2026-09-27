#!/usr/bin/env python3
"""The binding check — does the surround still attach to what the upstream chart creates?

    ./tests/binding.py [app ...]        default: every app under apps/

This is the test history/design/10-verification.md calls "the test this architecture needs and a
chart-per-app architecture did not", and it is the one that pays for adr/0012.

The gap it closes: our surround SELECTS INTO workloads that a different release created.
If an upstream bump renames a Service or a component label, *our* rendered output does not
change at all — so the golden files match, render-diff is clean, kubeconform passes, and
the routes point at nothing. Every other check in this repo is green while the site is
down.

So this one renders the upstream release and the surround release TOGETHER and asserts:

  * every route backendRef resolves to a Service that exists, on the port it declares;
  * the upstream release emits none of the kinds the surround owns — a PDB, ServiceMonitor,
    HPA or NetworkPolicy from both releases means two objects selecting the same pods, and
    two PDBs on one workload is a drain that hangs;
  * the upstream release emits no Ingress, because we route with Gateway API and an Ingress
    left enabled is a second, unauthenticated way in.

Upstream charts come from the pins the control plane renders (charts/control-plane/templates/
sources.yaml), so this checks the version that is actually deployed. Needs network.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

# Kinds the surround owns. Two objects of these selecting the same pods is the failure.
SURROUND_OWNED = {"PodDisruptionBudget", "ServiceMonitor", "HorizontalPodAutoscaler", "NetworkPolicy"}


def check_app(app: str, srcs: dict) -> list[str]:
    """The app as the cluster builds it (profile and substitution included), every
    HelmRelease rendered against its chart."""
    problems: list[str] = []
    docs = render.apps("medium", [app])
    upstream: list[dict] = []
    surround: list[dict] = []
    plain = [d for d in docs if d.get("kind") not in {"HelmRelease", "Kustomization"}]

    for rel in (d for d in docs if d.get("kind") == "HelmRelease"):
        name, ns = rel["metadata"]["name"], rel["metadata"]["namespace"]
        try:
            values = render.values_of(rel, docs)
            chart = render.chart_for(rel, srcs)
        except RuntimeError as e:
            problems.append(f"{app}/{name}: {e}")
            continue
        if chart is None:
            problems.append(f"{app}/{name}: chartRef did not resolve to a chart under charts/")
            continue
        try:
            (surround if render.local_chart(rel) else upstream).extend(render.helm_template(chart, name, ns, values))
        except RuntimeError as e:
            problems.append(f"{app}/{name}: {e}")

    # --- every backendRef must resolve -----------------------------------------------------
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
                    problems.append(
                        f"{app}: HTTPRoute/{route} routes to Service {n!r}, which no release creates"
                    )
                elif p is not None and p not in services[n]:
                    have = sorted(services[n]) or "no ports at all"
                    problems.append(
                        f"{app}: HTTPRoute/{route} routes to {n}:{p}, but that Service exposes {have}"
                    )

    # --- the upstream release must not emit what the surround owns -------------------------
    for d in upstream:
        k = d.get("kind")
        if k in SURROUND_OWNED:
            problems.append(
                f"{app}: the upstream release emits {k}/{d['metadata']['name']} — "
                f"the surround owns that kind, and two of them selecting the same pods is a drain that hangs"
            )
        if k == "Ingress":
            problems.append(
                f"{app}: the upstream release emits Ingress/{d['metadata']['name']} — "
                f"routing is Gateway API here, and a live Ingress is a second way in"
            )

    counts = f"{len(upstream)} upstream + {len(surround)} surround + {len(plain)} plain objects"
    print(f"   {app:12} {counts}, {len(services)} services")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("apps", nargs="*")
    args = ap.parse_args()

    srcs = render.sources()
    problems: list[str] = []
    print("== rendering upstream releases at their pinned versions")
    for app in args.apps or [a for a in render.APPS if (render.ROOT / "apps" / a / "release.yaml").exists()]:
        problems += check_app(app, srcs)

    print()
    if problems:
        print("== binding failures")
        for p in problems:
            print(f"   {p}")
        print(f"\nFAIL — {len(problems)} binding problem(s)")
        return 1
    print("OK — every route resolves, and no upstream release emits a surround-owned kind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
