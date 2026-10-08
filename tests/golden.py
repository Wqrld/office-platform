#!/usr/bin/env python3
"""Freeze what every case renders to, and fail when it changes.

    ./tests/golden.py            check every case against tests/golden/
    ./tests/golden.py --update   rewrite the goldens, for review in the diff

Goldens answer one question: *did this template change alter the output?* They are the only
check that notices a change nobody was looking for — a helper that stops emitting a label,
a `range` that drops its last element, a PDB that appears where none should.

A golden is not a judgement about whether the output is RIGHT. `--update` then reading the
diff is the intended workflow; the diff is the review.

## What is normalised, and why each one has to be

Nothing else is touched. Every normalisation here is a value that changes without the
templates changing, and each one would otherwise make the goldens churn until someone
deletes them:

  * `helm.sh/chart: platform-app-0.2.4` — release.sh rewrites the version in every
    Chart.yaml on every release, so an unnormalised golden fails on every single publish.
    That is the fastest way to teach people to run --update without reading the diff.

  * `ref: {tag: "v0.2.4"}` on the control plane's own source — the platform source is
    pinned at the chart's version, which moves for the same reason.
    Only a tag equal to the current chart version is replaced; an upstream pin is not.

  * `realm-<hash>` and `opensearch-security-<hash>` — platform-tenants hashes the chart
    version into these Job names so that every release runs them afresh (2.3.2), so they
    move on every publish too. What the hash covers is still in the golden in full: the
    realm ConfigMap's data and both Jobs' specs.

The chart NAME is kept. Only the version is replaced.
"""
import difflib
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
GOLDEN = HERE / "golden"

# platform-app-0.2.4 -> platform-app-<version>. Anchored to our own chart names so an
# upstream chart label passing through extraObjects is left alone.
CHART_LABEL = re.compile(r"^(\s*helm\.sh/chart:\s*)(platform-(?:deps|app|tenants))-\S+$", re.M)
# The platform-tenants Jobs whose names hash .Chart.Version (templates/keycloak.yaml,
# templates/opensearch.yaml).
JOB_HASH = re.compile(r"\b(realm|opensearch-security)-[0-9a-f]{10}\b")
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
    update = "--update" in sys.argv[1:]
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
    if failed:
        print(f"\nFAIL — {len(failed)} of {len(names)}: {', '.join(failed)}")
        print("If the change is intended: ./tests/golden.py --update, and put the diff in "
              "the commit.")
        return 1
    print(f"\nOK — {len(names)} cases match their goldens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
