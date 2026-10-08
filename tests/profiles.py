#!/usr/bin/env python3
"""Do the three sizes still say what they claim?

    ./tests/profiles.py [size ...]      default: small, medium and large

Renders every app and the platform layer at each size, as the cluster applies them, and
asserts: more than one replica has a PodDisruptionBudget selecting it and one replica has
none; every PDB uses `maxUnavailable` and selects a real pod template; every HPA sets
`maxReplicas`; datastore `instances` is HA at `large` only; Garage's `replication.factor` is
the same at every size. And for each sized release: every `valuesFrom` key exists at every
size, and no sizing key sits under `spec.values`, which beats `valuesFrom`. See `AGENTS.md`
(Checks, Sizing).
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
    """`docs` with every HelmRelease replaced by what it applies."""
    rendered = [d for d in docs if d.get("kind") != "HelmRelease"]
    for rel, out, err in render.releases(docs, srcs):
        if err:
            problems.append(f"{rel['metadata']['namespace']}/{rel['metadata']['name']}: {err}")
        rendered += out
    return rendered


def pod_labels(w: dict) -> dict:
    return ((w["spec"].get("template") or {}).get("metadata") or {}).get("labels") or {}


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
    dotted path -> value. `pdb: {enabled: false}` is not one: in an upstream release it is
    the surround owning budgets, at every size."""
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
    on the cluster reports. A replica count of 0 or 1 no size file sets is not a size:
    Collabora's and the SFU's one replica are correctness, Meet's zeros are not deployed."""
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

    workloads = [(w, n) for w, _, n in render.pod_specs(apps) if w.get("kind") in WORKLOAD_KINDS]
    pdbs = [d for d in apps if d.get("kind") == "PodDisruptionBudget"]
    hpas = [d for d in apps if d.get("kind") == "HorizontalPodAutoscaler"]

    # --- replicas and disruption budgets ---------------------------------------------------
    for w, replicas in workloads:
        ns, name = w["metadata"]["namespace"], w["metadata"]["name"]
        covering = [p for p in pdbs
                    if p["metadata"]["namespace"] == ns and selects(p["spec"].get("selector"), pod_labels(w))]
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
        matched = [w for w, _ in workloads
                   if w["metadata"]["namespace"] == ns and selects(spec.get("selector"), pod_labels(w))]
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sizes", nargs="*", help="small, medium, large; default: all three")
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

    return render.report(problems, f"{len(sizes)} sizes render, every replica count agrees with its "
                                   f"budget, every sized release has every size, and no release file "
                                   f"overrides one", "profile problem(s)")


if __name__ == "__main__":
    sys.exit(main())
