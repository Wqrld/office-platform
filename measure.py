#!/usr/bin/env python3
"""Add up what a size asks the scheduler for.

    ./measure.py render --size small [apps|platform] [--cluster default]

Renders every app and the platform layer at one size, as the cluster applies them, and sums
`resources.requests` over every container of every pod-bearing object times its replicas,
per namespace. Modelled rather than rendered, marked `~`: the pods of operator-owned CRs
(CNPG `Cluster`, `Keycloak`, `GarageCluster`), and the LimitRange default a container with
no requests is given. `!NO REQUESTS` is a BestEffort pod: no requests and no LimitRange.
Requests are what the scheduler admits on, not what will be used. See `AGENTS.md`.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "tests"))
import render  # noqa: E402

LAYERS = {"apps": render.apps, "platform": render.platform}
POD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}


def quantity(v):
    """Kubernetes quantity -> float in cores or bytes."""
    if v is None:
        return 0.0
    s = str(v).strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zA-Z]*)", s)
    if not m:
        return 0.0
    n, unit = float(m.group(1)), m.group(2)
    mult = {"": 1, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
            "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}
    return n * mult.get(unit, 1)


def operator_pods(doc: dict) -> tuple[int, dict] | None:
    """(replicas, requests) of an operator-owned CR, whose controller makes its pods."""
    spec = doc.get("spec") or {}
    if doc.get("kind") in ("Cluster", "Keycloak"):
        return spec.get("instances", 1), (spec.get("resources") or {}).get("requests") or {}
    if doc.get("kind") == "GarageCluster":                 # declares no resources
        return (spec.get("storage") or {}).get("replicas", 1), {}
    return None


def limitranges(docs):
    """namespace -> (cpu, memory) defaultRequest. Per namespace, not one global guess: a
    namespace with neither requests nor a LimitRange runs BestEffort pods, evicted first."""
    out = {}
    for d in docs:
        if d.get("kind") != "LimitRange":
            continue
        for item in d["spec"]["limits"]:
            if item.get("type") == "Container":
                dr = item.get("defaultRequest") or {}
                out[d["metadata"]["namespace"]] = (quantity(dr.get("cpu")), quantity(dr.get("memory")))
    return out


def charge(pod: dict, replicas: int, lr) -> tuple[float, float, str]:
    """(cpu, memory, note) for `replicas` of a pod, each container without requests charged
    its namespace's LimitRange default `lr`, if there is one."""
    cpu = mem = 0.0
    unset = 0
    for c in pod.get("containers", []) + pod.get("initContainers", []):
        req = (c.get("resources") or {}).get("requests") or {}
        unset += not req
        cpu, mem = cpu + quantity(req.get("cpu")), mem + quantity(req.get("memory"))
    if unset and lr:
        cpu, mem = cpu + lr[0] * unset, mem + lr[1] * unset
    return cpu * replicas, mem * replicas, "" if not unset else ("~limitrange" if lr else "!NO REQUESTS")


def pods(objects, lrs, prefix=""):
    """A row per pod-bearing object; helm test hooks are skipped, a reconcile never runs them."""
    for d, pod, replicas in render.pod_specs(objects):
        meta = d.get("metadata", {})
        if d.get("kind") in POD_KINDS and "test" not in (meta.get("annotations") or {}).get("helm.sh/hook", ""):
            ns = meta.get("namespace", "default")
            yield (ns, prefix + meta.get("name", "?"), *charge(pod, replicas, lrs.get(ns)))


def measure(layer, size, cluster):
    """(namespace, name, cpu, memory, note) for everything one layer schedules."""
    values = render.CASES / f"cluster-{cluster}.yaml"
    docs = LAYERS[layer](size, values=values)
    lrs = limitranges(docs)
    rows = list(pods([d for d in docs if d.get("kind") != "HelmRelease"], lrs))
    for rel, out, err in render.releases(docs, render.sources(values), ["--include-crds"]):
        ns, name = rel["metadata"]["namespace"], rel["metadata"]["name"]
        if err:
            rows.append((ns, f"{name} (render FAILED)", 0.0, 0.0, err.strip().splitlines()[-1][:80]))
        rows += pods(out, lrs, f"{name}/")
    for doc in docs:
        if got := operator_pods(doc):
            reps, req = got
            ns, lr = doc["metadata"].get("namespace", "default"), lrs.get(doc["metadata"].get("namespace"))
            if req:
                cpu, mem, note = quantity(req.get("cpu")), quantity(req.get("memory")), "~operator"
            elif lr:
                cpu, mem, note = lr[0], lr[1], "~limitrange"
            else:
                cpu, mem, note = 0.0, 0.0, "!NO REQUESTS"
            rows.append((ns, f"{doc['metadata']['name']} ({doc['kind']})", cpu * reps, mem * reps, note))
    return rows


def report(rows, label):
    by_ns = {}
    for ns, name, cpu, mem, note in rows:
        by_ns.setdefault(ns, []).append((name, cpu, mem, note))
    tc = tm = 0.0
    print(f"\n=== {label} ===")
    for ns in sorted(by_ns):
        nc = sum(r[1] for r in by_ns[ns])
        nm = sum(r[2] for r in by_ns[ns])
        tc, tm = tc + nc, tm + nm
        print(f"\n{ns}   {nc * 1000:.0f}m  {nm / 2**20:.0f}Mi")
        for name, cpu, mem, note in sorted(by_ns[ns]):
            print(f"    {name:<46} {cpu * 1000:>6.0f}m {mem / 2**20:>7.0f}Mi  {note}")
    print(f"\n{'TOTAL':<50} {tc * 1000:>6.0f}m {tm / 2**20:>7.0f}Mi")
    return tc, tm


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="per-namespace request totals")
    r.add_argument("layers", nargs="*", choices=list(LAYERS), help="default: both")
    r.add_argument("--size", default="medium", choices=render.SIZES)
    r.add_argument("--cluster", default="default", help="a cluster case: tests/cases/cluster-<name>.yaml")
    args = ap.parse_args()

    totals = {}
    for layer in args.layers or list(LAYERS):
        label = f"{layer} @ {args.size}"
        totals[label] = report(measure(layer, args.size, args.cluster), label)
    if len(totals) > 1:
        print("\n=== profiles ===")
        for label, (cpu, mem) in totals.items():
            print(f"  {label:<34} {cpu * 1000:>6.0f}m  {mem / 2**20:>7.0f}Mi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
