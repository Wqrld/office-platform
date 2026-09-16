#!/usr/bin/env python3
"""Build everything a cluster would apply, the way Flux does, and leave it where the other
checks can read it.

    ./tests/build.py [outdir]        default: a temp dir, printed on the last line

One directory per control-plane case in tests/cases/index.yaml — the clusters — and one
file per Flux Kustomization the control plane emits, plus `control-plane.yaml` for the
control plane itself. Nothing is hardcoded: the layers, their paths, their size components
and the enabled apps are all read from the rendered chart, so a cluster that turns an app
off or runs external S3 is built exactly as it would reconcile.

Two invariants ride along. The application table in charts/control-plane/templates/
_helpers.tpl and the directories under apps/ must agree exactly — an app in one and not
the other is either undeployable or unmentionable. And the check that pays for this script
on its own: **no ${VAR} may survive**. A typo'd `${BASE_DOMIAN}` is an error nowhere —
Flux leaves an unknown variable alone, kustomize is happy, the API server accepts it, and
the app comes up serving "docs.${BASE_DOMIAN}", which resolves for nobody.
"""
import pathlib
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402


def app_table_agrees() -> list[str]:
    tpl = (render.CHART / "templates" / "_helpers.tpl").read_text()
    body = tpl.split('{{- define "platform.apps" -}}')[1].split("{{- end }}")[0]
    table, dirs = set(yaml.safe_load(body)), set(render.APPS)
    return [f"in the app table but not under apps/: {sorted(table - dirs)}"] * bool(table - dirs) + \
           [f"under apps/ but not in the app table: {sorted(dirs - table)}"] * bool(dirs - table)


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="built-")).resolve()
    allowed = render.keycloak_placeholders()
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
            (out / cluster / f"{name}.yaml").write_text(yaml.safe_dump_all(objects, sort_keys=False))
            print(f"   {name:16} {len(objects):3} objects")
            leftover += [f"{cluster}/{name}: ${{{v}}}" for v in sorted(render.unresolved(objects, allowed))]

    print("\n== unresolved substitutions")
    if leftover:
        print("\n".join(f"   {hit}" for hit in leftover))
        print("\nFAIL — a variable is used but the control plane does not emit it into cluster-vars.")
        print("Flux leaves an unknown ${VAR} untouched, so it reaches the cluster as a literal.")
        return 1
    print(f"   none ({len(allowed)} Keycloak placeholders allowed by name)\n\n{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
