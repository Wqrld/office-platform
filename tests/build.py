#!/usr/bin/env python3
"""Does every layer of every cluster build, with no `${VAR}` left unresolved?

    ./tests/build.py [outdir]        default: a temp dir, printed on the last line

Builds each cluster case (the control-plane cases in tests/cases/index.yaml) as Flux would,
into `<outdir>/<cluster>/<kustomization>.yaml`, everything read from the rendered control
plane. Fails on a build error, on a `${VAR}` that survived substitution (Flux leaves an
unknown one alone, and the app serves `docs.${BASE_DOMIAN}`), and when the app table, the
directories under apps/ and examples/cluster.yaml disagree, when a release's chart
source is missing from sources.yaml or from updatecli, or when monitoring stops being a
leaf (adr/0119). See `AGENTS.md` (Checks).
"""
import argparse
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

# Apps no user opens by hand, so no switcher entry: Collabora is an iframe inside Drive, Find
# an API Docs calls, LiveKit media. Every other app is in the switcher, or it is unreachable
# from the others.
NO_SWITCHER = {"collabora", "find", "livekit"}
# Chart sources moved by hand on purpose: updatecli/updatecli.d/livekit.yaml says why.
HAND_PINNED = {"livekit-helm"}


def app_table_agrees() -> list[str]:
    apps = render.load((render.CHART / "apps.yaml").read_text())
    table, dirs = set(apps), set(render.APPS)
    problems = [f"in the app table but not under apps/: {sorted(table - dirs)}"] * bool(table - dirs) + \
               [f"under apps/ but not in the app table: {sorted(dirs - table)}"] * bool(dirs - table)
    example = next(d for d in render.load_all((render.ROOT / "examples" / "cluster.yaml").read_text())
                   if d and d["kind"] == "HelmRelease")
    chosen = set(example["spec"]["values"]["apps"])
    choosable = {n for n, a in apps.items() if not a.get("internal")}
    if chosen != choosable:
        problems.append(f"examples/cluster.yaml `apps` should name exactly {sorted(choosable)}, "
                        f"names {sorted(chosen)}")
    for name, app in sorted(apps.items()):
        if app.get("internal") == ("default" in app):
            problems.append(f"{name}: an internal app has no `default`, every other app has one")
        entry = app.get("switcher")
        if (name in NO_SWITCHER) != (entry is None):
            problems.append(f"{name}: a switcher entry is {'not ' if entry else ''}expected (tests/build.py NO_SWITCHER)")
        elif entry and (set(entry) != {"name", "logo", "maturity"} or not app.get("hosts")):
            problems.append(f"{name}: switcher needs exactly name, logo, maturity, and a host to serve the logo from")
    return problems


def pins_are_tracked() -> list[str]:
    """Every source an app's release reads exists, and updatecli bumps it: a git source's url
    is in an updatecli/updatecli.d/ pattern, a Helm repository's chart in updatecli/values.yaml."""
    srcs = render.sources()
    patterns = "".join(p.read_text() for p in (render.ROOT / "updatecli" / "updatecli.d").glob("*.yaml"))
    charts = render.load((render.ROOT / "updatecli" / "values.yaml").read_text())["charts"]
    problems = []
    for rel_file in sorted((render.ROOT / "apps").glob("*/release.yaml")):
        where = rel_file.relative_to(render.ROOT).as_posix()
        for rel in render.load_all(rel_file.read_text()):
            ref = (((rel or {}).get("spec", {}).get("chart") or {}).get("spec") or {}).get("sourceRef")
            if not ref:
                continue
            src = srcs.get(ref["name"])
            if ref["name"] in HAND_PINNED:
                continue
            if src is None:
                problems.append(f"{where}: source {ref['name']} is not in templates/sources.yaml")
                continue
            url = src["spec"]["url"]
            if src["kind"] == "GitRepository" and url not in patterns and url.replace(".", "\\.") not in patterns:
                problems.append(f"{where}: no updatecli/updatecli.d/ pattern names {url}")
            if src["kind"] == "HelmRepository" and not any(
                    c["repo"].rstrip("/") == url.rstrip("/") and where in c["files"] for c in charts):
                problems.append(f"{where}: updatecli/values.yaml has no entry for {url} pinning this file")
    return sorted(set(problems))


MONITORING = {"cluster-monitoring", "monitoring"}
# What `monitoring.mode: none` may change: the two layers, and these.
MONITORING_VARS = {"MONITORING_MODE", "ALERT_EMAIL", "PROBE_TARGETS"}


def monitoring_is_a_leaf(built: dict[str, dict[str, list[dict]]]) -> list[str]:
    """adr/0119: nothing outside the two monitoring layers emits a monitoring CRD, nothing
    waits for them, `none` changes no other layer, and the rules keep their templates."""
    problems = []
    for cluster, layers in built.items():
        for name, objects in layers.items():
            for o in objects:
                if name not in MONITORING and o["apiVersion"].startswith("monitoring.coreos.com/"):
                    problems.append(f"{cluster}/{name}: {o['kind']}/{o['metadata']['name']} is a monitoring "
                                    "object outside the monitoring layers")
                deps = {d["name"] for d in (o.get("spec") or {}).get("dependsOn") or []} & MONITORING
                if o["kind"] == "Kustomization" and deps - ({"cluster-monitoring"} if o["metadata"]["name"] ==
                                                             "monitoring" else set()):
                    problems.append(f"{cluster}: Kustomization {o['metadata']['name']} depends on {sorted(deps)}")
                if o["kind"] == "PrometheusRule" and "$labels" not in render.dump(o):
                    problems.append(f"{cluster}/{name}: PrometheusRule/{o['metadata']['name']} lost its $labels "
                                    "to substitution")
                if o["kind"] == "Probe" and not isinstance(o["spec"]["targets"]["staticConfig"]["static"], list):
                    problems.append(f"{cluster}/{name}: the Probe's targets are not a list")

    def strip(layers):
        out = {k: v for k, v in layers.items() if k not in MONITORING}
        out["control-plane"] = [
            {**o, "data": {k: v for k, v in o["data"].items() if k not in MONITORING_VARS}}
            if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "cluster-vars" else o
            for o in layers["control-plane"] if not (o["kind"] == "Kustomization" and o["metadata"]["name"] in MONITORING)
            and not (o["kind"] == "HelmRepository" and o["metadata"]["name"] == "prometheus-community")]
        return render.dump(out)
    if "default" in built and "none" in built and strip(built["default"]) != strip(built["none"]):
        problems.append("cluster-none differs from cluster-default outside the monitoring layers and vars")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir", nargs="?", type=pathlib.Path, help="default: a temp dir")
    args = ap.parse_args()
    out = (args.outdir or pathlib.Path(tempfile.mkdtemp(prefix="built-"))).resolve()
    leftover: list[str] = []
    built: dict[str, dict[str, list[dict]]] = {}

    print("== application table")
    if problems := app_table_agrees():
        return render.report(problems, "", "disagreement(s) between apps.yaml, apps/ and examples/cluster.yaml")
    print("   agrees with apps/")
    print("== pins")
    if problems := pins_are_tracked():
        return render.report(problems, "", "release source(s) nothing pins or bumps")
    print("   every release's source is in sources.yaml and bumped by updatecli")

    for values in render.clusters():
        cluster = values.stem.removeprefix("cluster-")
        print(f"== {cluster}")
        try:
            layers = render.cluster(values)
        except RuntimeError as e:
            print(f"   BUILD FAILED\n{e}")
            return 1
        built[cluster] = layers
        (out / cluster).mkdir(parents=True, exist_ok=True)
        for name, objects in layers.items():
            (out / cluster / f"{name}.yaml").write_text(render.dump_all(objects, sort_keys=False))
            print(f"   {name:16} {len(objects):3} objects")
            leftover += [f"{cluster}/{name}: ${{{v}}}" for v in sorted(render.unresolved(objects))]

    print("\n== monitoring is a leaf")
    if problems := monitoring_is_a_leaf(built):
        return render.report(problems, "", "way(s) monitoring reaches into the other layers")
    print("   nothing depends on it, and none changes nothing else")

    print("\n== unresolved substitutions")
    return render.report(leftover, f"every cluster builds, nothing unresolved\n{out}",
                         "variable(s) used but not in cluster-vars: Flux leaves them as literals")


if __name__ == "__main__":
    sys.exit(main())
