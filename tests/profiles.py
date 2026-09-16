#!/usr/bin/env python3
"""Do the size profiles still say what they claim to say?

    ./tests/profiles.py [size ...]      default: small, medium and large

The 5-to-5,000 claim rests on three overlays that nothing else checks, and an overlay is the
easiest thing in this repo to get silently wrong: a patch whose target path a chart does not
have is a no-op, not an error, and a PDB selector that matches nothing is an object that
protects zero pods while looking exactly like protection.

So this renders each profile the way the cluster would — Flux builds each app and the
platform layer with the profile as a component, then `helm template` every HelmRelease
against its pinned chart — and asserts the four invariants from 10-verification.md:

  * `replicas > 1` implies a PodDisruptionBudget that actually selects those pods;
  * `replicas == 1` implies NO PodDisruptionBudget selects them (the small profile is the
    one most likely to regress, and a budget on a single replica blocks every drain);
  * every PDB uses `maxUnavailable`, and every PDB selector matches a real pod template;
  * an HPA, where one exists, sets `maxReplicas`.

Plus two the datastores need, since the platform layer carries a profile too: `instances`
is HA at `large` and single elsewhere, and Garage's `replication.factor` is IDENTICAL across
all three — it cannot be changed in place, so a profile that appears to raise it is a promise
of redundancy nothing delivers.

And two set differences. Every HelmRelease that sizes itself must appear in the `small`
profile: a missing stanza is not an error anywhere — the app just runs at production size
in a demo. And every patch target in every profile must match an object that exists: since
the profile is applied per app, a typo'd target is a silent no-op in every one of them,
and nothing but this notices.

Chart resolution is imported from binding.py rather than copied: the pins are read from the
rendered control plane and one reader of them is enough. Needs network, like the binding
check, for the same reason.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import binding  # noqa: E402  — the chart-resolution half of this check already exists there
import render  # noqa: E402

HERE = render.ROOT
WORKLOAD_KINDS = {"Deployment", "StatefulSet"}
# Operator-owned CRs whose `instances` is the replica count. Their controllers make the pods
# and their own PDBs, so they are read from the spec rather than rendered.
INSTANCE_KINDS = {"Cluster", "Keycloak"}
HA_SIZE = "large"


def render_releases(docs: list[dict], srcs: dict, work: pathlib.Path, variables: dict,
                    problems: list[str]) -> list[dict]:
    """Every HelmRelease in `docs`, rendered. Non-release objects are passed through."""
    rendered = [d for d in docs if d.get("kind") != "HelmRelease"]
    for rel in [d for d in docs if d.get("kind") == "HelmRelease"]:
        name, ns = rel["metadata"]["name"], rel["metadata"]["namespace"]
        values = render.substitute(rel["spec"].get("values") or {}, variables)
        chart = binding.local_chart(rel)
        if chart is None and rel["spec"].get("chartRef"):
            problems.append(f"{ns}/{name}: chartRef did not resolve under charts/")
            continue
        if chart is None:
            try:
                chart = binding.fetch_upstream(rel, srcs, work)
            except Exception as e:                                   # noqa: BLE001
                problems.append(f"{ns}/{name}: {e}")
                continue
        if chart is None:
            problems.append(f"{ns}/{name}: neither chart nor chartRef")
            continue
        if binding.local_chart(rel) and not (pathlib.Path(chart) / "charts").exists():
            subprocess.run(["helm", "dependency", "build", chart],
                           check=True, capture_output=True, text=True)
        try:
            out = binding.helm_template(chart, name, ns, values)
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
    if not match and not (selector or {}).get("matchExpressions"):
        return False        # an empty selector matches every pod in the namespace
    return all(labels.get(k) == v for k, v in match.items())


def sets_resources(node) -> bool:
    if isinstance(node, dict):
        return "resources" in node or any(sets_resources(v) for v in node.values())
    if isinstance(node, list):
        return any(sets_resources(v) for v in node)
    return False


def small_profile_covers_every_app() -> list[str]:
    """Every HelmRelease that sizes itself must be sized by the `small` profile.

    This is the failure this layout can actually have, and it is a set difference rather
    than a judgement call: a missing stanza is not an error anywhere — the app simply runs
    at production size in a demo, and the first symptom is a node that will not schedule.
    apps/overlays/README.md names this as the check worth having; this is it.
    """
    profile = yaml.safe_load((HERE / "apps" / "overlays" / "size-small" / "kustomization.yaml").read_text())
    targets = {(t.get("kind"), t.get("name"), t.get("namespace"))
               for t in ((p or {}).get("target") or {} for p in profile.get("patches", []))}

    problems = []
    for f in sorted((HERE / "apps").glob("*/*.yaml")):
        for d in yaml.safe_load_all(f.read_text()):
            if not d or d.get("kind") != "HelmRelease":
                continue
            if not sets_resources(d["spec"].get("values") or {}):
                continue
            key = ("HelmRelease", d["metadata"]["name"], d["metadata"]["namespace"])
            if key not in targets:
                problems.append(
                    f"small: {key[2]}/{key[1]} sets resources but the small profile does not "
                    f"patch it — it would run at production size in a demo, which fails as a "
                    f"pod that never schedules rather than as anything that mentions sizing")
    return problems


def every_target_matches(size: str, objects: list[dict]) -> list[str]:
    """Every patch in a profile must target something in the whole-set render.

    Kustomize no-ops a patch whose target matches nothing, and the profile is applied to one
    app at a time — so a typo'd name is not "invisible in the whole-set build", it is a
    no-op in every per-app build too, with no output anywhere that says so.
    """
    present = {(d["kind"], d["metadata"]["name"], d["metadata"].get("namespace")) for d in objects}
    problems = []
    for layer in ("apps", "platform"):
        profile = yaml.safe_load((HERE / layer / "overlays" / f"size-{size}" / "kustomization.yaml").read_text())
        for t in ((p or {}).get("target") or {} for p in profile.get("patches") or []):
            key = (t.get("kind"), t.get("name"), t.get("namespace"))
            if key not in present:
                problems.append(f"{size}: {layer}/overlays targets {key[0]} {key[2]}/{key[1]}, which nothing "
                                f"renders — the patch is a silent no-op")
    return problems


def check(size: str, srcs: dict, work: pathlib.Path, variables: dict) -> tuple[list[str], dict]:
    problems: list[str] = []

    raw_apps, raw_platform = render.apps(size), render.platform(size)
    problems += every_target_matches(size, raw_apps + raw_platform)
    apps = render_releases(render.substitute(raw_apps, variables), srcs, work, variables, problems)
    platform = render_releases(render.substitute(raw_platform, variables), srcs, work, variables, problems)

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
    srcs = binding.sources()
    variables = binding.variables()
    work = pathlib.Path(tempfile.mkdtemp(prefix="profiles-"))
    problems: list[str] = []
    garages: dict[str, dict] = {}

    try:
        print("== rendering each profile")
        for size in sizes:
            found, garage = check(size, srcs, work, variables)
            problems += found
            garages[size] = garage
        problems += small_profile_covers_every_app()
    finally:
        shutil.rmtree(work, ignore_errors=True)

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
    print(f"OK — {len(sizes)} profiles render, every replica count agrees with its budget, "
          f"and the small profile sizes every app that sizes itself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
