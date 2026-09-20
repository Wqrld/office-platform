#!/usr/bin/env python3
"""Does values.schema.json still reject what it is there to reject?

    ./tests/schema.py

Helm validates values on every render, so the positive direction is covered by the cases.
This is the other direction: a schema that has only ever seen valid input is
indistinguishable from an absent one, and an absent one lets a typo'd key silently do
nothing — the most common Helm failure mode. Every file under tests/fixtures/schema/<chart>/
must fail to render, with the error its `# expect:` line names; failing for another reason
is not a pass. The control plane's fixtures also cover its template-time refusals.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

FIXTURES = render.ROOT / "tests" / "fixtures" / "schema"


def main() -> int:
    fail = False
    print("== schema files")
    for chart in sorted(p for p in (render.ROOT / "charts").iterdir() if p.is_dir()):
        schema = chart / "values.schema.json"
        if not schema.exists():
            print(f"   {chart.name}: NO values.schema.json — its values are unchecked"); fail = True
            continue
        try:
            json.loads(schema.read_text())
            print(f"   {chart.name:16} valid JSON")
        except ValueError as e:
            print(f"   {chart.name}: values.schema.json is not valid JSON: {e}"); fail = True

    print("\n== values that must be rejected")
    for chart_dir in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        chart = chart_dir.name
        if not (render.ROOT / "charts" / chart).is_dir():
            print(f"   fixtures for unknown chart {chart}"); fail = True
            continue
        for f in sorted(chart_dir.glob("*.yaml")):
            first = f.read_text().splitlines()[0]
            expect = first.removeprefix("# expect: ") if first.startswith("# expect: ") else ""
            label = f"   {chart:20} {f.stem:38}"
            if not expect:
                print(f"{label} no `# expect:` line"); fail = True
                continue
            try:
                render.helm_template_text(render.ROOT / "charts" / chart, "rejected", "office-schema", f)
                print(f"{label} RENDERED — the schema no longer rejects it"); fail = True
            except RuntimeError as e:
                if expect in str(e):
                    print(f"{label} rejected: {expect}")
                else:
                    print(f"{label} rejected, but not for its reason\n      expected: {expect}\n"
                          f"      got:      {' '.join(str(e).split())[:160]}"); fail = True

    if fail:
        print("\nFAIL — the schema is not catching what it is supposed to catch.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
