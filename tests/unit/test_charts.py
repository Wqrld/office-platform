"""Static checks on the charts' sources that need no render."""
import json
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHARTS = sorted(d for d in (ROOT / "charts").iterdir() if (d / "Chart.yaml").is_file())


def define(path: pathlib.Path, name: str) -> str:
    text = path.read_text()
    m = re.search(r'\{\{- define "' + re.escape(name) + r'" -\}\}.*?\{\{- end -\}\}', text, re.S)
    assert m, f"{path.relative_to(ROOT)} defines no {name}"
    return m.group(0)


# No library chart (history/design/adr/0002), so the shared helpers are copies: they must
# stay identical, or the surround's selectors stop matching what deps and tenants label.
@pytest.mark.parametrize("name, files", [
    ("platform.labels", ["platform-deps/templates/_helpers.tpl", "platform-app/templates/_app.tpl",
                         "platform-tenants/templates/_helpers.tpl"]),
    ("platform.app", ["platform-deps/templates/_helpers.tpl", "platform-app/templates/_app.tpl"]),
])
def test_shared_helpers_identical(name, files):
    bodies = {f: define(ROOT / "charts" / f, name) for f in files}
    assert len(set(bodies.values())) == 1, bodies


def keys(values, schema, path=""):
    """Paths in `values` the schema does not declare, and declared paths `values` lacks."""
    defs = schema.get("$defs", {})
    def walk(v, s, path):
        if "$ref" in s:
            s = defs[s["$ref"].rsplit("/", 1)[-1]]
        props = s.get("properties")
        if props is None or not isinstance(v, dict):
            return []
        out = [f"{path}{k}: not in the schema" for k in v if k not in props]
        out += [f"{path}{k}: not in values.yaml" for k in props if k not in v]
        return out + [p for k in props.keys() & v.keys() for p in walk(v[k], props[k], f"{path}{k}.")]
    return walk(values, schema, path)


@pytest.mark.parametrize("chart", CHARTS, ids=lambda c: c.name)
def test_values_and_schema_agree(chart):
    schema = json.loads((chart / "values.schema.json").read_text())
    values = yaml.safe_load((chart / "values.yaml").read_text())
    assert keys(values, schema) == []


def tpl_yaml(name: str) -> dict:
    body = define(ROOT / "charts/platform-deps/templates/_profiles.tpl", name)
    return yaml.safe_load(body.split("-}}", 1)[1].rsplit("{{-", 1)[0])


def test_every_profile_and_family_is_used():
    profiles, families = tpl_yaml("platform.profiles"), tpl_yaml("platform.families")
    deps = [yaml.safe_load(p.read_text())["spec"]["values"] for p in ROOT.glob("apps/*/deps.yaml")]
    used_families = {d["env"] for d in deps if d.get("env")}
    assert used_families <= families.keys(), "a deps file names a family that does not exist"
    assert families.keys() <= used_families, f"unused families: {families.keys() - used_families}"
    used = {(kind, p) for f in families.values() for kind, p in f.items()}
    used |= {(kind, d[kind]["env"]) for d in deps for kind in profiles
             if isinstance(d.get(kind), dict) and d[kind].get("env")}
    defined = {(kind, p) for kind, ps in profiles.items() for p in ps}
    assert used <= defined, f"named but not defined: {used - defined}"
    assert defined <= used, f"defined but used by nothing: {defined - used}"
