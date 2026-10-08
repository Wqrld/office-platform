#!/usr/bin/env python3
"""Build everything a cluster would apply, the way Flux does, and leave it where the other
checks can read it.

    ./tests/build.py [outdir]        default: a temp dir, printed on the last line

One directory per control-plane case in tests/cases/index.yaml — the clusters — and one
file per Flux Kustomization the control plane emits, plus `control-plane.yaml` for the
control plane itself. Nothing is hardcoded: the layers, their paths, their size components
and the enabled apps are all read from the rendered chart, so a cluster that turns an app
off or runs external S3 is built exactly as it would reconcile.

Two invariants ride along. The application table, charts/control-plane/apps.yaml, and
the directories under apps/ must agree exactly — an app in one and not the other is either
undeployable or unmentionable — and examples/cluster.yaml, the file an organisation copies,
must name every app it can choose. And the check that pays for this script
on its own: **no ${VAR} may survive**. A typo'd `${BASE_DOMIAN}` is an error nowhere —
Flux leaves an unknown variable alone, kustomize is happy, the API server accepts it, and
the app comes up serving "docs.${BASE_DOMIAN}", which resolves for nobody.
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

# Apps no user opens by hand, so no switcher entry: Collabora is an iframe inside Drive, Find
# an API Docs calls, LiveKit media. Every other app is in the switcher, or it is unreachable
# from the others.
NO_SWITCHER = {"collabora", "find", "livekit"}


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


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="built-")).resolve()
    leftover: list[str] = []

    print("== application table")
    if problems := app_table_agrees():
        print("\n".join(f"   {p}" for p in problems) + "\nFAIL")
        return 1
    print("   agrees with apps/")

    for values in render.clusters():
        cluster = values.stem.removeprefix("cluster-")
        print(f"== {cluster}")
        try:
            layers = render.cluster(values)
        except RuntimeError as e:
            print(f"   BUILD FAILED\n{e}")
            return 1
        (out / cluster).mkdir(parents=True, exist_ok=True)
        for name, objects in layers.items():
            (out / cluster / f"{name}.yaml").write_text(render.dump_all(objects, sort_keys=False))
            print(f"   {name:16} {len(objects):3} objects")
            leftover += [f"{cluster}/{name}: ${{{v}}}" for v in sorted(render.unresolved(objects))]

    print("\n== unresolved substitutions")
    if leftover:
        print("\n".join(f"   {hit}" for hit in leftover))
        print("\nFAIL — a variable is used but the control plane does not emit it into cluster-vars.")
        print("Flux leaves an unknown ${VAR} untouched, so it reaches the cluster as a literal.")
        return 1
    print(f"   none\n\n{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
