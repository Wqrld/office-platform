#!/usr/bin/env python3
"""Do the size profiles still say what they claim to say?

    ./tests/profiles.py [size ...]      default: small, medium and large

The 5-to-5,000 claim rests on three sizes per app (apps/<app>/sizes/) that nothing else
checks, and a PDB selector that matches nothing is an object that protects zero pods while
looking exactly like protection.

So this renders each size the way the cluster would — Flux builds each app with `SIZE`
substituted and the platform layer with its profile component, then `helm template` every
HelmRelease against its pinned chart with its `valuesFrom` sizes merged in — and asserts
the four invariants from history/design/10-verification.md:

  * `replicas > 1` implies a PodDisruptionBudget that actually selects those pods;
  * `replicas == 1` implies NO PodDisruptionBudget selects them (the small profile is the
    one most likely to regress, and a budget on a single replica blocks every drain);
  * every PDB uses `maxUnavailable`, and every PDB selector matches a real pod template;
  * an HPA, where one exists, sets `maxReplicas`.

Plus two the datastores need, since the platform layer carries a profile too: `instances`
is HA at `large` and single elsewhere, and Garage's `replication.factor` is IDENTICAL across
all three — it cannot be changed in place, so a profile that appears to raise it is a promise
of redundancy nothing delivers.

And two set differences on the sized releases. Every `valuesFrom` key must exist at every
size — what `values_of` fails on for one size, checked for all three at once. And no sizing
key may sit under `spec.values`: `spec.values` beats `valuesFrom`, so a `resources`, a
`pdb` block or a replica count a size file also sets would silently override it. A replica
count of 0 or 1 that NO size file sets is not a size — Collabora's and the SFU's one
replica are correctness, and Meet's zeros are workloads not deployed — and `pdb: {enabled:
false}` in an upstream release is the surround owning budgets, at every size.

Needs network, like the binding check: the pinned upstream charts are rendered.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

WORKLOAD_KINDS = {"Deployment", "StatefulSet"}
# Operator-owned CRs whose `instances` is the replica count. Their controllers make the pods
# and their own PDBs, so they are read from the spec rather than rendered.
INSTANCE_KINDS = {"Cluster", "Keycloak"}
HA_SIZE = "large"


def render_releases(docs: list[dict], srcs: dict, problems: list[str]) -> list[dict]:
    """Every HelmRelease in `docs`, rendered. Non-release objects are passed through."""
    rendered = [d for d in docs if d.get("kind") != "HelmRelease"]
    for rel in [d for d in docs if d.get("kind") == "HelmRelease"]:
        name, ns = rel["metadata"]["name"], rel["metadata"]["namespace"]
        try:
            chart = render.chart_for(rel, srcs)
            if chart is None:
                raise RuntimeError("chartRef did not resolve under charts/")
            out = render.helm_template(chart, name, ns, render.values_of(rel, docs))
        except RuntimeError as e:
            problems.append(f"{ns}/{name}: {e}")
            continue
        # `helm template` leaves metadata.namespace off any object whose chart does not set
        # it; the API server fills it in from the release. Do the same, or every object from
        # a chart that omits it looks like it belongs to no namespace and matches no PDB.
        for d in out:
            d.setdefault("metadata", {}).setdefault("namespace", ns)
        rendered += out
    return rendered


def selects(selector: dict, labels: dict) -> bool:
    match = (selector or {}).get("matchLabels") or {}
    exprs = (selector or {}).get("matchExpressions") or []
    if not match and not exprs:
        return False        # an empty selector matches every pod in the namespace
    ops = {"In": lambda k, v: labels.get(k) in v,
           "NotIn": lambda k, v: labels.get(k) not in v,
           "Exists": lambda k, v: k in labels,
           "DoesNotExist": lambda k, v: k not in labels}
    return (all(labels.get(k) == v for k, v in match.items())
            and all(ops[e["operator"]](e["key"], e.get("values", [])) for e in exprs))


def sizing_keys(node, path: str = "") -> dict[str, object]:
    """Every `resources`, `replicas`/`replicaCount` and `pdb` under a values tree, as
    dotted path -> value. `pdb: {enabled: false}` is not one (see the docstring)."""
    found = {}
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}" if path else k
            if k in ("resources", "replicas", "replicaCount") or (k == "pdb" and v != {"enabled": False}):
                found[here] = v
            else:
                found |= sizing_keys(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found |= sizing_keys(v, f"{path}[{i}]")
    return found


def sized_releases() -> list[str]:
    """The two set differences on every HelmRelease that carries a `valuesFrom` size key.
    `spec.values` beating `valuesFrom` is the one failure this layout can have that nothing
    on the cluster reports, so it is asserted here rather than judged."""
    problems = []
    for app in render.APPS:
        docs = render.flux_build(f"apps/{app}")
        cms = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ConfigMap"}
        for rel in (d for d in docs if d.get("kind") == "HelmRelease"):
            name, sized = rel["metadata"]["name"], {}
            for ref in rel["spec"].get("valuesFrom") or []:
                keys = (cms.get(ref["name"]) or {}).get("data") or {}
                for size in render.SIZES:
                    want = ref.get("valuesKey", "values.yaml").replace("${SIZE}", size)
                    if want not in keys:
                        problems.append(f"{app}: {name} reads {ref['name']}[{want}], which is not in "
                                        f"the build (has {sorted(keys)})")
                        continue
                    sized |= sizing_keys(render.load(keys[want]) or {})
            for key, value in sizing_keys(rel["spec"].get("values") or {}).items():
                if key in sized:
                    problems.append(f"{app}: {name} sets `{key}` under spec.values, which beats the "
                                    f"sizes/ files that also set it")
                elif rel["spec"].get("valuesFrom") and not (key.split(".")[-1] != "resources" and value in (0, 1)):
                    problems.append(f"{app}: {name} sets `{key}` under spec.values and no size file "
                                    f"sizes it — it is the same at every size, which sizes/ should say")
    return problems


def check(size: str, srcs: dict) -> tuple[list[str], dict]:
    problems: list[str] = []

    raw_apps, raw_platform = render.apps(size), render.platform(size)
    apps = render_releases(raw_apps, srcs, problems)
    platform = render_releases(raw_platform, srcs, problems)

    workloads = [d for d in apps if d.get("kind") in WORKLOAD_KINDS]
    pdbs = [d for d in apps if d.get("kind") == "PodDisruptionBudget"]
    hpas = [d for d in apps if d.get("kind") == "HorizontalPodAutoscaler"]

    # --- replicas and disruption budgets ---------------------------------------------------
    for w in workloads:
        ns, name = w["metadata"]["namespace"], w["metadata"]["name"]
        replicas = w["spec"].get("replicas", 1)
        labels = ((w["spec"].get("template") or {}).get("metadata") or {}).get("labels") or {}
        covering = [p for p in pdbs
                    if p["metadata"]["namespace"] == ns and selects(p["spec"].get("selector"), labels)]
        if replicas > 1 and not covering:
            problems.append(
                f"{size}: {ns}/{name} runs {replicas} replicas with no PodDisruptionBudget "
                f"selecting it — a node drain takes the whole component at once")
        if replicas == 1 and covering:
            names = ", ".join(p["metadata"]["name"] for p in covering)
            problems.append(
                f"{size}: {ns}/{name} runs a single replica but is selected by PDB {names} — "
                f"on one replica a budget is a drain that never completes")

    for p in pdbs:
        ns, name = p["metadata"]["namespace"], p["metadata"]["name"]
        spec = p["spec"]
        if "minAvailable" in spec:
            problems.append(
                f"{size}: PDB {ns}/{name} uses minAvailable — the surround emits maxUnavailable "
                f"only, because minAvailable on a shrinking workload blocks every drain")
        if "maxUnavailable" not in spec:
            problems.append(f"{size}: PDB {ns}/{name} sets neither maxUnavailable nor minAvailable")
        matched = [w for w in workloads
                   if w["metadata"]["namespace"] == ns
                   and selects(spec.get("selector"),
                               ((w["spec"].get("template") or {}).get("metadata") or {}).get("labels") or {})]
        if not matched:
            problems.append(
                f"{size}: PDB {ns}/{name} selects no pod template in its namespace — it protects "
                f"nothing, and looks exactly like protection (labels: "
                f"{(spec.get('selector') or {}).get('matchLabels')})")

    for h in hpas:
        if not h["spec"].get("maxReplicas"):
            problems.append(f"{size}: HPA {h['metadata']['namespace']}/{h['metadata']['name']} "
                            f"sets no maxReplicas — an autoscaler with no ceiling")

    # --- the datastores the profile also sizes ----------------------------------------------
    instances: dict[str, int] = {}
    for d in platform:
        if d.get("kind") in INSTANCE_KINDS and "instances" in (d.get("spec") or {}):
            key = f"{d['metadata']['namespace']}/{d['kind']}/{d['metadata']['name']}"
            instances[key] = d["spec"]["instances"]
            ha = d["spec"]["instances"] > 1
            if size == HA_SIZE and not ha:
                problems.append(f"{size}: {key} still runs a single instance — the profile that "
                                f"claims 500-5,000 people has no datastore redundancy")
            if size != HA_SIZE and ha:
                problems.append(f"{size}: {key} runs {d['spec']['instances']} instances — the "
                                f"small and medium profiles are explicitly single-node")

    garage = {f"{d['metadata']['namespace']}/{d['metadata']['name']}":
              ((d.get("spec") or {}).get("replication") or {}).get("factor")
              for d in platform if d.get("kind") == "GarageCluster"}

    print(f"   {size:8} {len(workloads)} workloads, {len(pdbs)} PDBs, "
          f"instances: {instances or 'none'}, garage replication: {garage or 'none'}")
    return problems, garage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sizes", nargs="*")
    args = ap.parse_args()

    sizes = args.sizes or list(render.SIZES)
    srcs = render.sources()
    problems: list[str] = []
    garages: dict[str, dict] = {}

    print("== rendering each profile")
    for size in sizes:
        found, garage = check(size, srcs)
        problems += found
        garages[size] = garage
    problems += sized_releases()

    # Garage's replication factor cannot be changed in place: raising it is a rebuild of the
    # cluster, not a profile patch. A profile that appears to raise it promises a redundancy
    # nothing delivers, so the three must agree.
    for cluster in {c for g in garages.values() for c in g}:
        factors = {size: g.get(cluster) for size, g in garages.items()}
        if len(set(factors.values())) > 1:
            problems.append(
                f"GarageCluster {cluster} has a different replication.factor per profile "
                f"({factors}) — it cannot be changed in place, so only the value it was "
                f"created with is real")

    print()
    if problems:
        print("== profile failures")
        for p in problems:
            print(f"   {p}")
        print(f"\nFAIL — {len(problems)} profile problem(s)")
        return 1
    print(f"OK — {len(sizes)} sizes render, every replica count agrees with its budget, "
          f"every sized release has every size, and no release file overrides one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
