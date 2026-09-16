"""Render this repository the way the cluster does. Every check imports this.

Two mechanisms, both real rather than approximated:

  * `flux_build(path, components)` — kustomize-build one layer with `flux build`, the same
    code kustomize-controller runs. It matters that this is Flux's build and not
    `kubectl kustomize`: Flux builds with no load restriction, which is what lets
    `apps/drive` generate a ConfigMap from `../switcher.js`, and it is Flux that applies
    `spec.components` — the size profile — on top of the path.

  * `control_plane(values)` — `helm template` the control-plane chart, which is the only
    thing an organisation's cluster reads from this repo directly. Everything else is
    reached through the Kustomizations it emits, so `cluster(values)` follows them: it
    builds each one at the path and components it declares and substitutes the
    `cluster-vars` ConfigMap the chart rendered, exactly as `postBuild.substituteFrom`
    would. That is the whole cluster, from one values file, with nothing hardcoded here.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHART = ROOT / "charts" / "control-plane"
CASES = ROOT / "tests" / "cases"
SIZES = ("small", "medium", "large")
# Every application directory. The control-plane chart carries the same list with each
# app's dependencies and hosts; tests/build.py asserts the two agree.
APPS = sorted(d.name for d in (ROOT / "apps").iterdir() if (d / "kustomization.yaml").is_file())

VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def docs_in(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def run(cmd: list[str], **kw) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed:\n{out.stderr}")
    return out.stdout


def flux_build(path: str, components: list[str] = (), name: str = "build") -> list[dict]:
    """kustomize-build `path` (relative to the repo root) as Flux would, profile included."""
    ks = {"apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
          "metadata": {"name": name, "namespace": "flux-system"},
          "spec": {"interval": "1h", "prune": True, "path": f"./{path}",
                   "components": list(components),
                   "sourceRef": {"kind": "OCIRepository", "name": "office-config"}}}
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(ks, f)
    try:
        # `--path` resolves against the current directory, not the kustomization file.
        out = run(["flux", "build", "kustomization", name, "--path", f"./{path}",
                   "--kustomization-file", f.name, "--dry-run"], cwd=ROOT)
    finally:
        pathlib.Path(f.name).unlink()
    return docs_in(out)


def apps(size: str, names: list[str] = APPS) -> list[dict]:
    """Every application at one size — the union of the per-app layers."""
    return [d for a in names for d in flux_build(f"apps/{a}", [f"../overlays/size-{size}"], f"app-{a}")]


def platform(size: str) -> list[dict]:
    return (flux_build("platform", [f"./overlays/size-{size}"], "platform")
            + flux_build("platform/objectstore", [f"../overlays/size-{size}"], "objectstore"))


def substitute(node, variables: dict[str, str]):
    """What postBuild.substituteFrom does, the way Flux does it: on the YAML text, so a
    variable can stand in for a whole value (`dnsNames: ${TLS_HOSTS}` becomes a list).
    Unknown variables are left alone, not blanked; `$${X}` is the escape for a literal
    `${X}`, which is how Keycloak's own placeholders get through."""
    text = yaml.safe_dump(node).replace("$${", "\0")
    text = VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), text)
    return yaml.safe_load(text.replace("\0", "${"))


def clusters() -> list[pathlib.Path]:
    """The values file of every control-plane case in tests/cases/index.yaml — the clusters."""
    index = yaml.safe_load((CASES / "index.yaml").read_text())["cases"]
    return [CASES / f"{c['name']}.yaml" for c in index if c["chart"] == "control-plane"]


def control_plane(values: pathlib.Path, extra: list[str] = ()) -> list[dict]:
    """`helm template` the control-plane chart with an organisation's values, exactly as
    tests/render.sh renders its cases."""
    return docs_in(run(["helm", "template", "platform", str(CHART), "--namespace", "flux-system",
                        "--kube-version", "1.34.2", "--values", str(values), *extra]))


def cluster(values: pathlib.Path) -> dict[str, list[dict]]:
    """Everything a cluster with these values would apply, keyed by Flux Kustomization.

    The control plane itself is under the key `control-plane`; each Kustomization it emits
    is built at its declared path and components and substituted from the rendered
    `cluster-vars`, then keyed by its name.
    """
    cp = control_plane(values)
    variables = next(d["data"] for d in cp if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cluster-vars")
    layers = {"control-plane": cp}
    for ks in (d for d in cp if d["kind"] == "Kustomization"):
        name, spec = ks["metadata"]["name"], ks["spec"]
        built = flux_build(spec["path"].removeprefix("./"), spec.get("components", []), name)
        layers[name] = substitute(built, variables)
    return layers


def unresolved(objects: list[dict], allowed: set[str] = frozenset()) -> set[str]:
    """`${VAR}`s that survived substitution. Flux leaves an unknown one untouched, so it
    reaches the cluster as a literal and the app serves `docs.${BASE_DOMIAN}` to nobody."""
    return set(VAR.findall(yaml.safe_dump_all(objects))) - set(allowed)


def keycloak_placeholders() -> set[str]:
    """Keycloak's own `$${NAME}` placeholders look like unresolved Flux variables after the
    build — on purpose (platform/identity/realm.yaml). Allowed by name, read from the realm."""
    names: set[str] = set()
    for d in docs_in((ROOT / "platform/identity/realm.yaml").read_text()):
        if d.get("kind") == "KeycloakRealmImport":
            names |= set(d["spec"].get("placeholders") or {})
    return names
