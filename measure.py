#!/usr/bin/env python3
"""
Render a size profile and add up what it asks the scheduler for.

The 5-to-5,000 claim, and the narrower "a demo fits on a spare node" claim, both rest on
numbers nobody has ever added up. This adds them up.

    ./measure.py fetch                        # populate the chart cache from sources.yaml
    ./measure.py render environments/small    # per-namespace request totals
    ./measure.py compare environments/medium apps
                                              # assert two paths render identically

What it does, in order: `kubectl kustomize` the path, substitute the cluster vars the way
Flux's postBuild would, `helm template` every HelmRelease against its pinned chart, and sum
`resources.requests` over every container of every pod-bearing object, multiplied by its
replica count.

Two things it models rather than renders, because an operator creates their pods and no
amount of templating will produce them: CNPG `Cluster`, Keycloak `Keycloak` and
`GarageCluster` (instances x declared resources), and the LimitRange default that a
container with no requests of its own will be given. Both are marked `~` in the output.
That is the honest boundary of this tool — it measures what is REQUESTED, which is what the
scheduler admits on, and it does not predict what will actually be used.
"""
import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
CACHE = ROOT / ".charts"

POD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}
# Operator-owned CRs: their pods come from a controller, so they are modelled from the
# spec rather than rendered. Kind -> (replica field, resources field).
OPERATOR_KINDS = {
    "Cluster": ("instances", "resources"),
    "Keycloak": ("instances", "resources"),
    "GarageCluster": (None, None),
}


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


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


def load_vars(cluster):
    """The postBuild substitution map, read from the cluster's vars.yaml."""
    path = ROOT / "clusters" / cluster / "vars.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()).get("data", {})


def substitute(text, variables):
    """Flux postBuild, near enough. `$${X}` escapes to a literal `${X}` and is left alone."""
    text = text.replace("$${", "\0ESC\0")
    for key, value in variables.items():
        text = text.replace("${" + key + "}", str(value))
    # An unresolved ${...} would break the YAML parse or silently blank a value; neither is
    # something to discover halfway down a sum.
    left = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text))
    if left:
        print(f"warning: unsubstituted variables: {', '.join(sorted(left))}", file=sys.stderr)
    return text.replace("\0ESC\0", "${")


# ---------------------------------------------------------------- chart resolution

def sources(cluster):
    """(kind, name) -> source spec, read from the cluster's sources.yaml. The pins live
    there and nowhere else; this tool must not carry a second copy of them."""
    path = ROOT / "clusters" / cluster / "sources.yaml"
    out = {}
    for doc in yaml.safe_load_all(path.read_text()):
        if doc:
            out[(doc["kind"], doc["metadata"]["name"])] = doc["spec"]
    return out


def fetch(cluster):
    """Populate the chart cache. Everything is pinned, so this is reproducible."""
    CACHE.mkdir(exist_ok=True)
    srcs = sources(cluster)
    for (kind, name), spec in srcs.items():
        target = CACHE / name
        if target.exists():
            print(f"  cached  {name}")
            continue
        if kind == "GitRepository":
            tag = spec["ref"]["tag"]
            print(f"  git     {name} @ {tag}")
            sh(["git", "clone", "--depth", "1", "--branch", tag, "--filter=blob:none",
                "--sparse", spec["url"], str(target)])
            sh(["git", "sparse-checkout", "set", "src/helm"], cwd=target)
        elif kind == "HelmRepository":
            if spec.get("type") == "oci":
                # An OCI registry is not a repository index; `helm template` resolves
                # oci:// refs directly, so there is nothing to add.
                print(f"  oci     {name}")
                continue
            print(f"  repo    {name} -> {spec['url']}")
            # --force-update: this runs against whatever helm repos the machine already
            # has, and a stale entry under the same name is otherwise a hard failure.
            sh(["helm", "repo", "add", "--force-update", name, spec["url"]])
        else:
            # OCIRepository: our own charts in Harbor, which needs credentials this tool
            # has no business holding. platform-app/platform-deps create no pods anyway —
            # they are routes, policies and secrets — so their absence costs nothing here.
            print(f"  skip    {name} ({kind})")
    sh(["helm", "repo", "update"])


def chart_for(release, srcs):
    """Locate the chart a HelmRelease names. Returns (ref, extra helm args) or None."""
    spec = release["spec"]
    if "chartRef" in spec:
        return None                                    # OCIRepository — see fetch()
    cs = spec["chart"]["spec"]
    ref = cs["sourceRef"]
    src = srcs.get((ref["kind"], ref["name"]))
    if src is None:
        return None
    if ref["kind"] == "GitRepository":
        path = CACHE / ref["name"] / cs["chart"]
        return (str(path), []) if path.exists() else None
    if ref["kind"] == "HelmRepository":
        return (f"{ref['name']}/{cs['chart']}", ["--version", cs["version"]])
    return None


# ---------------------------------------------------------------- summation

def requests_of(pod_spec):
    cpu = mem = 0.0
    unset = 0
    for c in pod_spec.get("containers", []) + pod_spec.get("initContainers", []):
        req = (c.get("resources") or {}).get("requests") or {}
        if not req:
            unset += 1
        cpu += quantity(req.get("cpu"))
        mem += quantity(req.get("memory"))
    return cpu, mem, unset


def walk(doc):
    """(cpu, memory, replicas, containers-without-requests) for one rendered object."""
    kind = doc.get("kind")
    if kind not in POD_KINDS:
        return None
    # Helm test hooks only ever run under `helm test`. Counting them inflates every total
    # by a pod per chart that will never be scheduled by a reconcile.
    hooks = (doc.get("metadata", {}).get("annotations") or {}).get("helm.sh/hook", "")
    if "test" in hooks:
        return None
    if kind == "CronJob":
        spec = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        replicas = 1
    elif kind == "Pod":
        spec, replicas = doc["spec"], 1
    else:
        spec = doc["spec"]["template"]["spec"]
        replicas = doc["spec"].get("replicas", 1)
    cpu, mem, unset = requests_of(spec)
    return cpu * replicas, mem * replicas, replicas, unset


def limitranges(docs):
    """namespace -> (cpu, memory) defaultRequest, read from the render itself.

    A container with no requests is charged the LimitRange of ITS namespace, or nothing at
    all if that namespace has none. Guessing one global default would hide the case worth
    seeing: a namespace with neither requests nor a LimitRange, whose pods are BestEffort
    and are the first thing the kubelet evicts.
    """
    out = {}
    for d in docs:
        if d.get("kind") != "LimitRange":
            continue
        for item in d["spec"]["limits"]:
            if item.get("type") != "Container":
                continue
            dr = item.get("defaultRequest") or {}
            out[d["metadata"]["namespace"]] = (quantity(dr.get("cpu")),
                                               quantity(dr.get("memory")))
    return out


def render(path, cluster, fallback):
    variables = load_vars(cluster)
    srcs = sources(cluster)
    raw = sh(["kubectl", "kustomize", str(ROOT / path)])
    docs = [d for d in yaml.safe_load_all(substitute(raw, variables)) if d]
    lrs = limitranges(docs)

    rows = []            # (namespace, name, cpu, memory, note)
    for doc in docs:
        kind, meta = doc.get("kind"), doc.get("metadata", {})
        ns = meta.get("namespace", "default")
        name = meta.get("name", "?")

        if kind == "HelmRelease":
            resolved = chart_for(doc, srcs)
            if resolved is None:
                rows.append((ns, f"{name} (chart not resolvable)", 0.0, 0.0, "skip"))
                continue
            ref, extra = resolved
            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as vf:
                yaml.safe_dump(doc["spec"].get("values", {}), vf)
                vf.flush()
                try:
                    out = sh(["helm", "template", name, ref, "-n", ns, "-f", vf.name,
                              "--include-crds"] + extra)
                except subprocess.CalledProcessError as exc:
                    rows.append((ns, f"{name} (render FAILED)", 0.0, 0.0,
                                 exc.stderr.strip().splitlines()[-1][:80]))
                    continue
            for sub in yaml.safe_load_all(out):
                if not sub:
                    continue
                got = walk(sub)
                if got:
                    cpu, mem, reps, unset = got
                    lr = lrs.get(ns)
                    if unset and lr:
                        cpu += lr[0] * reps * unset
                        mem += lr[1] * reps * unset
                    note = "" if not unset else ("~limitrange" if lr else "!NO REQUESTS")
                    rows.append((ns, f"{name}/{sub['metadata']['name']}", cpu, mem, note))
            continue

        if kind in OPERATOR_KINDS:
            reps_field, res_field = OPERATOR_KINDS[kind]
            spec = doc.get("spec", {})
            reps = spec.get(reps_field, 1) if reps_field else \
                spec.get("storage", {}).get("replicas", 1)
            req = ((spec.get(res_field) or {}).get("requests") or {}) if res_field else {}
            lr = lrs.get(ns)
            if req:
                cpu, mem, note = quantity(req.get("cpu")), quantity(req.get("memory")), "~operator"
            elif lr:
                cpu, mem, note = lr[0], lr[1], "~limitrange"
            else:
                cpu, mem, note = 0.0, 0.0, "!NO REQUESTS"
            rows.append((ns, f"{name} ({kind})", cpu * reps, mem * reps, note))
            continue

        got = walk(doc)
        if got:
            cpu, mem, reps, unset = got
            lr = lrs.get(ns)
            if unset and lr:
                cpu += lr[0] * reps * unset
                mem += lr[1] * reps * unset
            rows.append((ns, name, cpu, mem,
                         "" if not unset else ("~limitrange" if lr else "!NO REQUESTS")))
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


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch");   f.add_argument("--cluster", default="prod")
    r = sub.add_parser("render")
    r.add_argument("paths", nargs="+")
    r.add_argument("--cluster", default="prod")

    c = sub.add_parser("compare")
    c.add_argument("a"); c.add_argument("b"); c.add_argument("--cluster", default="prod")
    args = ap.parse_args()

    if args.cmd == "fetch":
        fetch(args.cluster)
        return 0

    if args.cmd == "compare":
        va = sh(["kubectl", "kustomize", str(ROOT / args.a)])
        vb = sh(["kubectl", "kustomize", str(ROOT / args.b)])
        if va == vb:
            print(f"IDENTICAL  {args.a} == {args.b}")
            return 0
        print(f"DIFFERS    {args.a} != {args.b}")
        return 1

    totals = {}
    for path in args.paths:
        totals[path] = report(render(path, args.cluster, None), path)
    if len(totals) > 1:
        print("\n=== profiles ===")
        for path, (cpu, mem) in totals.items():
            print(f"  {path:<34} {cpu * 1000:>6.0f}m  {mem / 2**20:>7.0f}Mi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
