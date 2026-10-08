#!/usr/bin/env python3
"""Did this template change alter the output?

    ./tests/golden.py            check every case against tests/golden/
    ./tests/golden.py --update   rewrite the goldens, for review in the diff

Renders every case in tests/cases/index.yaml and fails on any difference from its golden,
or on a golden with no case. A golden says nothing about whether the output is right: the
diff after `--update` is the review. Only values that change on every release without a
template changing are normalised (below). See `AGENTS.md` (Checks).
"""
import argparse
import difflib
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
GOLDEN = HERE / "golden"

# Normalised, because release.sh moves them on every publish and a golden that fails on every
# release teaches --update without reading. Chart labels: platform-app-0.2.4 -> -<version>,
# anchored to our own charts so an upstream label passing through extraObjects is kept.
CHART_LABEL = re.compile(r"^(\s*helm\.sh/chart:\s*)(platform-(?:deps|app|tenants))-\S+$", re.M)
# The platform-tenants Jobs whose names hash .Chart.Version, to run afresh on every release
# (templates/keycloak.yaml, templates/opensearch.yaml); what the hash covers is kept in full.
JOB_HASH = re.compile(r"\b(realm|opensearch-security)-[0-9a-f]{10}\b")
# The control plane's own source is pinned at the chart version; an upstream pin is kept.
VERSION = re.search(r"^version: (\S+)", (HERE.parent / "charts/control-plane/Chart.yaml").read_text(), re.M).group(1)


def normalise(text: str) -> str:
    text = CHART_LABEL.sub(r"\1\2-<version>", text)
    text = JOB_HASH.sub(r"\1-<hash>", text)
    return text.replace(f'tag: "v{VERSION}"', 'tag: "v<version>"')


def rendered(name: str) -> str:
    try:
        return normalise(render.render_case(name))
    except RuntimeError as e:
        sys.exit(f"golden: rendering {name} failed:\n{e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--update", action="store_true", help="rewrite the goldens, for review in the diff")
    update = ap.parse_args().update
    GOLDEN.mkdir(exist_ok=True)

    names = [c["name"] for c in render.cases()]
    stale = {p.name for p in GOLDEN.glob("*.yaml")} - {f"{n}.yaml" for n in names}
    failed = []

    for name in names:
        got = rendered(name)
        path = GOLDEN / f"{name}.yaml"

        if update:
            existed = path.exists()
            before = path.read_text() if existed else None
            path.write_text(got)
            state = "unchanged" if before == got else ("updated" if existed else "new")
            print(f"{state:9} {name}")
            continue

        if not path.exists():
            print(f"NO GOLDEN {name}  — run ./tests/golden.py --update")
            failed.append(name)
            continue

        want = path.read_text()
        if want == got:
            print(f"MATCH     {name}")
        else:
            failed.append(name)
            print(f"CHANGED   {name}")
            diff = difflib.unified_diff(
                want.splitlines(True), got.splitlines(True),
                fromfile=f"golden/{name}.yaml", tofile=f"rendered/{name}.yaml",
            )
            sys.stdout.writelines(diff)

    for s in sorted(stale):
        # A golden with no case is a case someone deleted. Left in place it looks like
        # coverage that does not exist.
        print(f"ORPHAN    {s}  — no such case in tests/cases/index.yaml")
        if update:
            (GOLDEN / s).unlink()
            print(f"removed   {s}")
        else:
            failed.append(s)

    if update:
        print(f"\n{len(names)} goldens written to tests/golden/. Read the diff.")
        return 0
    return render.report(failed, f"{len(names)} cases match their goldens",
                         f"of {len(names)} changed; if intended: ./tests/golden.py --update, and put "
                         f"the diff in the commit")


if __name__ == "__main__":
    sys.exit(main())
