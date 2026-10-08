#!/usr/bin/env python3
"""Do the schemas, and the control plane's refusals, still reject a bad values file?

    ./tests/schema.py

Helm validates values on every render, so the cases cover the accepting direction; a schema
that has only seen valid input is indistinguishable from none. Every chart must have a valid
values.schema.json, and every file under tests/fixtures/schema/<chart>/ must fail to render
with the error its first line, `# expect: <text>`, names: failing for another reason is not
a pass. See `AGENTS.md` (Checks).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

FIXTURES = render.ROOT / "tests" / "fixtures" / "schema"


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    problems: list[str] = []
    print("== schema files")
    for chart in sorted(p for p in (render.ROOT / "charts").iterdir() if p.is_dir()):
        schema = chart / "values.schema.json"
        if not schema.exists():
            problems.append(f"{chart.name}: no values.schema.json — its values are unchecked")
            continue
        try:
            json.loads(schema.read_text())
            print(f"   {chart.name:16} valid JSON")
        except ValueError as e:
            problems.append(f"{chart.name}: values.schema.json is not valid JSON: {e}")

    print("\n== values that must be rejected")
    for chart_dir in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        chart = chart_dir.name
        if not (render.ROOT / "charts" / chart).is_dir():
            problems.append(f"fixtures for unknown chart {chart}")
            continue
        for f in sorted(chart_dir.glob("*.yaml")):
            first = f.read_text().splitlines()[0]
            expect = first.removeprefix("# expect: ") if first.startswith("# expect: ") else ""
            where = f"{chart}/{f.stem}"
            if not expect:
                problems.append(f"{where}: no `# expect:` line")
                continue
            try:
                render.helm_template_text(render.ROOT / "charts" / chart, "rejected", "office-schema", f)
                problems.append(f"{where}: RENDERED — the schema no longer rejects it")
            except RuntimeError as e:
                if expect in str(e):
                    print(f"   {chart:20} {f.stem:38} rejected: {expect}")
                else:
                    problems.append(f"{where}: rejected, but not for its reason\n      expected: {expect}\n"
                                    f"      got:      {' '.join(str(e).split())[:160]}")
    return render.report(problems, "every schema rejects what it is there to reject", "schema problem(s)")


if __name__ == "__main__":
    sys.exit(main())
