#!/usr/bin/env python3
"""Render this repository the way the cluster does. Every check imports this.

    ./tests/render.py <case>      one case from tests/cases/index.yaml, to stdout
    ./tests/render.py --list      case names

Three mechanisms, all real rather than approximated:

  * `flux_build(path, components)` — kustomize-build one layer with `flux build`, the same
    code kustomize-controller runs: no load restriction (so `apps/drive` can generate a
    ConfigMap from `../switcher.js`), and `spec.components` applied where a layer has them.

  * `values_of(release, objects)` — a HelmRelease's effective values: what helm-controller
    merges from its `valuesFrom` ConfigMaps (the app's sizes, `apps/<app>/sizes/`) under
    `spec.values`. Every check that templates a release goes through it, so a size that is
    not in the ConfigMap fails here the way it fails there.

  * `control_plane(values)` — `helm template` the control-plane chart with an
    organisation's values, the only thing a cluster reads from this repo directly.
    `cluster(values)` follows the Kustomizations it emits: builds each at the path and
    components it declares, substituted from the rendered `cluster-vars` exactly as
    `postBuild` would. That is the whole cluster from one values file, nothing hardcoded.

Upstream charts (`fetch_upstream`) come from the pins the control plane renders, cached
under .charts/ — the checks that need them (binding, profiles, check-secrets, startup,
measure) need network.
"""
from __future__ import annotations

import functools
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

# libyaml's parser and emitter; the pure-Python ones were four fifths of a build.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
def load(text): return yaml.load(text, Loader=_LOADER)
def load_all(text): return yaml.load_all(text, Loader=_LOADER)
def dump(data, stream=None, **kw): return yaml.dump(data, stream, Dumper=_DUMPER, **kw)
def dump_all(docs, **kw): return yaml.dump_all(docs, Dumper=_DUMPER, **kw)

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHART = ROOT / "charts" / "control-plane"
CASES = ROOT / "tests" / "cases"
CACHE = ROOT / ".charts"
DEFAULT = CASES / "cluster-default.yaml"
# cluster-default with every app on, off-by-default ones included — what the per-app checks render,
# so an app off by default is still checked rather than silently absent.
FULL = CASES / "cluster-full.yaml"
SIZES = ("small", "medium", "large")
# Every application directory. The control-plane chart carries the same list with each
# app's dependencies and hosts; tests/build.py asserts the two agree.
APPS = sorted(d.name for d in (ROOT / "apps").iterdir() if (d / "kustomization.yaml").is_file())

# Pinned so a render never consults a live cluster: a golden that changes with whatever
# cluster the operator points at is not a golden. Keep in step with the clusters you run.
KUBE_VERSION = os.environ.get("KUBE_VERSION", "1.34.2")
# The CRD groups the cluster has. A chart that gates an object on
# `.Capabilities.APIVersions.Has` must see here what it sees there.
API_VERSIONS = ["gateway.networking.k8s.io/v1", "cert-manager.io/v1", "external-secrets.io/v1",
                "postgresql.cnpg.io/v1", "gateway.envoyproxy.io/v1alpha1"]

VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def docs_in(text: str) -> list[dict]:
    return [d for d in load_all(text) if d]


def run(cmd: list[str], **kw) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed:\n{out.stderr}")
    return out.stdout


# ---------------------------------------------------------------- helm

def helm_template_text(chart: str, release: str, ns: str, values: str | pathlib.Path,
                       extra: list[str] = ()) -> str:
    cmd = ["helm", "template", release, str(chart), "--namespace", ns,
           "--kube-version", KUBE_VERSION, "--values", str(values), *extra]
    cmd += [a for api in API_VERSIONS for a in ("--api-versions", api)]
    return run(cmd)


def helm_template(chart: str, release: str, ns: str, values: dict, extra: list[str] = ()) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        dump(values, f)
    try:
        return docs_in(helm_template_text(chart, release, ns, f.name, extra))
    finally:
        pathlib.Path(f.name).unlink()


def cases() -> list[dict]:
    return load((CASES / "index.yaml").read_text())["cases"]


def case(name: str) -> dict:
    for c in cases():
        if c["name"] == name:
            return c
    sys.exit(f"render: no case '{name}' in tests/cases/index.yaml")


def render_case(name: str) -> str:
    """One case as `helm template` prints it: chart, release and namespace from the index,
    never defaulted — both land in the output, and a defaulted namespace is whatever the
    operator's kubectl context happens to be. `tenantsFrom: <cluster case>` layers that
    cluster's TENANTS_JSON on as `apps`, the way platform/tenants.yaml does, so the tenants
    golden renders the real table and not a copy of it."""
    c = case(name)
    args = (ROOT / "charts" / c["chart"], c["release"], c["namespace"], CASES / f"{name}.yaml")
    if not (src := c.get("tenantsFrom")):
        return helm_template_text(*args)
    apps = json.loads(variables(CASES / f"{src}.yaml")["TENANTS_JSON"])
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump({"apps": apps}, f)
    try:
        return helm_template_text(*args, ["--values", f.name])
    finally:
        pathlib.Path(f.name).unlink()


# ---------------------------------------------------------------- flux

def flux_build(path: str, components: list[str] = (), name: str = "build") -> list[dict]:
    """kustomize-build `path` (relative to the repo root) as Flux would, profile included."""
    ks = {"apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
          "metadata": {"name": name, "namespace": "flux-system"},
          "spec": {"interval": "1h", "prune": True, "path": f"./{path}",
                   "components": list(components),
                   "sourceRef": {"kind": "GitRepository", "name": "office-config"}}}
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        dump(ks, f)
    try:
        # `--path` resolves against the current directory, not the kustomization file.
        out = run(["flux", "build", "kustomization", name, "--path", f"./{path}",
                   "--kustomization-file", f.name, "--dry-run"], cwd=ROOT)
    finally:
        pathlib.Path(f.name).unlink()
    return docs_in(out)


def substitute(node, variables: dict[str, str]):
    """What postBuild does, the way Flux does it: on the YAML text, so a variable can stand
    in for a whole value (`dnsNames: ${TLS_HOSTS}` becomes a list). Unknown variables are
    left alone; `$${X}` escapes a literal `${X}`, which is how Keycloak's placeholders pass."""
    text = dump(node).replace("$${", "\0")
    text = VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), text)
    return load(text.replace("\0", "${"))


def clusters() -> list[pathlib.Path]:
    """The values file of every control-plane case — the clusters."""
    return [CASES / f"{c['name']}.yaml" for c in cases() if c["chart"] == "control-plane"]


@functools.cache
def control_plane(values: pathlib.Path, extra: tuple[str, ...] = ()) -> list[dict]:
    """`helm template` the control-plane chart with an organisation's values."""
    return docs_in(helm_template_text(CHART, "platform", "flux-system", values, list(extra)))


def variables(values: pathlib.Path = DEFAULT, extra: tuple[str, ...] = ()) -> dict[str, str]:
    """The cluster's `cluster-vars`, as the control plane renders them."""
    return next(d["data"] for d in control_plane(values, extra)
                if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cluster-vars")


def sources(values: pathlib.Path = DEFAULT) -> dict[str, dict]:
    """name -> source object: the pins live in the control plane and nowhere else."""
    return {d["metadata"]["name"]: d for d in control_plane(values)
            if d["kind"] in {"GitRepository", "HelmRepository", "OCIRepository"}}


def build(ks: dict, variables: dict[str, str]) -> list[dict]:
    """One emitted Kustomization, built at its path and components and substituted."""
    spec = ks["spec"]
    built = flux_build(spec["path"].removeprefix("./"), spec.get("components", []), ks["metadata"]["name"])
    return substitute(built, variables | spec.get("postBuild", {}).get("substitute", {}))


def merge(base: dict, over: dict) -> dict:
    """Helm's values merge: maps deep, everything else — lists included — replaced."""
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


@functools.cache
def _rendered_configmaps(released: str) -> tuple[dict, ...]:
    """The ConfigMaps one of our own charts renders — cached on the release as YAML, since
    every sized check asks for the same layer three times over."""
    rel = yaml.safe_load(released)
    ns = rel["metadata"]["namespace"]
    out = helm_template(local_chart(rel), rel["metadata"]["name"], ns, values_of(rel, []))
    return tuple(d | {"metadata": {"namespace": ns} | d["metadata"]} for d in out if d.get("kind") == "ConfigMap")


def layer_configmap(objects: list[dict], name: str, ns: str) -> dict | None:
    """A ConfigMap the layer applies, directly or — only when it has none by that name —
    through a release of one of our charts in it: the Valkey instances read their ACL users
    from the tenants release this way. Only local charts, so no upstream fetch, and only
    releases without a `valuesFrom` of their own, which keeps this from recursing."""
    def find(cms):
        return next((d for d in cms if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == name
                     and d["metadata"].get("namespace") == ns), None)
    if (cm := find(objects)) is not None:
        return cm
    for rel in objects:
        if rel.get("kind") == "HelmRelease" and local_chart(rel) and not rel["spec"].get("valuesFrom"):
            if (cm := find(_rendered_configmaps(yaml.safe_dump(rel)))) is not None:
                return cm
    return None


def values_of(rel: dict, objects: list[dict]) -> dict:
    """A HelmRelease's values as helm-controller computes them: each `valuesFrom` entry in
    order, then `spec.values` on top. Only ConfigMaps the same built layer applies are
    resolved — that is where the sizes live, and where the tenants release renders the
    Valkey ACLs (`layer_configmap`) — and a missing ConfigMap or key is an error, as it is
    on the cluster (no `optional: true` here, on purpose)."""
    spec, ns = rel["spec"], rel["metadata"]["namespace"]
    values: dict = {}
    for ref in spec.get("valuesFrom") or []:
        if ref.get("kind") != "ConfigMap":
            raise RuntimeError(f"{ns}/{rel['metadata']['name']}: valuesFrom {ref.get('kind')} is not resolved here")
        cm = layer_configmap(objects, ref["name"], ns)
        if cm is None:
            raise RuntimeError(f"{ns}/{rel['metadata']['name']}: valuesFrom ConfigMap {ref['name']} is not in the build")
        key = ref.get("valuesKey", "values.yaml")
        if key not in (cm.get("data") or {}):
            raise RuntimeError(f"{ns}/{rel['metadata']['name']}: ConfigMap {ref['name']} has no key {key!r} "
                               f"(has {sorted(cm.get('data') or {})})")
        values = merge(values, load(cm["data"][key]) or {})
    return merge(values, spec.get("values") or {})


def cluster(values: pathlib.Path, extra: tuple[str, ...] = ()) -> dict[str, list[dict]]:
    """Everything a cluster with these values would apply, keyed by Flux Kustomization;
    the control plane itself under `control-plane`."""
    cp = control_plane(values, extra)
    vars_ = variables(values, extra)
    return {"control-plane": cp} | {ks["metadata"]["name"]: build(ks, vars_)
                                    for ks in cp if ks["kind"] == "Kustomization"}


def apps(size: str, names: list[str] = APPS, values: pathlib.Path = FULL) -> list[dict]:
    """Every named application at one size, built the way the control plane says."""
    layers = cluster(values, ("--set", f"size={size}"))
    return [d for a in names for d in layers.get(f"app-{a}", [])]


def platform(size: str, values: pathlib.Path = DEFAULT) -> list[dict]:
    layers = cluster(values, ("--set", f"size={size}"))
    return layers["platform"] + layers.get("objectstore", [])


def unresolved(objects: list[dict], allowed: set[str] = frozenset()) -> set[str]:
    """`${VAR}`s that survived substitution. Flux leaves an unknown one untouched, so it
    reaches the cluster as a literal and the app serves `docs.${BASE_DOMIAN}` to nobody."""
    return set(VAR.findall(dump_all(objects))) - set(allowed)



# ---------------------------------------------------------------- upstream charts

def local_chart(rel: dict) -> str | None:
    """Our own charts, rendered from charts/ as the HelmChart the control plane builds them as."""
    ref = rel["spec"].get("chartRef")
    if not ref or ref["kind"] != "HelmChart":
        return None
    p = ROOT / "charts" / ref["name"]
    return str(p) if p.is_dir() else None


def git_checkout(url: str, ref: dict, dest: pathlib.Path) -> None:
    """Shallow-checkout a tag, or a bare commit (`--branch` rejects a SHA — Find's pin)."""
    if tag := ref.get("tag"):
        run(["git", "clone", "--depth", "1", "--branch", tag, "--quiet", url, str(dest)])
        return
    dest.mkdir(parents=True)
    for cmd in (["git", "init", "--quiet"],
                ["git", "remote", "add", "origin", url],
                ["git", "fetch", "--depth", "1", "--quiet", "origin", ref["commit"]],
                ["git", "checkout", "--quiet", "FETCH_HEAD"]):
        run(cmd, cwd=dest)


def fetch_upstream(rel: dict, srcs: dict) -> str | None:
    """A local path for a HelmRelease's pinned chart, fetched into .charts/ once."""
    spec = rel["spec"]
    if "chart" not in spec:
        return None                       # chartRef — one of ours
    cs = spec["chart"]["spec"]
    src = srcs.get(cs["sourceRef"]["name"])
    if src is None:
        raise RuntimeError(f"{rel['metadata']['name']}: no source {cs['sourceRef']['name']}")
    kind, sspec = src["kind"], src["spec"]

    if kind == "GitRepository":
        dest = CACHE / src["metadata"]["name"] / (sspec["ref"].get("tag") or sspec["ref"]["commit"])
        if not dest.exists():
            git_checkout(sspec["url"], sspec["ref"], dest)
        return str(dest / cs["chart"])

    if kind == "HelmRepository":
        dest = CACHE / src["metadata"]["name"] / cs["version"]
        if not (dest / cs["chart"]).is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            ref = [f"{sspec['url']}/{cs['chart']}"] if sspec.get("type") == "oci" \
                else [cs["chart"], "--repo", sspec["url"]]
            run(["helm", "pull", *ref, "--version", cs["version"], "--untar", "--untardir", str(dest)])
        return str(dest / cs["chart"])

    raise RuntimeError(f"unsupported source kind {kind}")


def chart_for(rel: dict, srcs: dict) -> str | None:
    """Local or upstream, whichever the HelmRelease names; None for a chartRef not in charts/."""
    return local_chart(rel) if rel["spec"].get("chartRef") else fetch_upstream(rel, srcs)


def release(rel: dict, objects: list[dict], srcs: dict) -> list[dict]:
    """What helm-controller applies for one HelmRelease: its chart at the pin, with its
    effective values, then its `postRenderers` — the kustomize patches and image overrides
    that Drive, Meet, Find and LiveKit use to reach inside upstream charts."""
    name, ns = rel["metadata"]["name"], rel["metadata"]["namespace"]
    chart = chart_for(rel, srcs)
    if chart is None:
        raise RuntimeError(f"{ns}/{name}: chartRef did not resolve to a chart under charts/")
    out = helm_template(chart, name, ns, values_of(rel, objects))
    for pr in rel["spec"].get("postRenderers") or []:
        k = {key: pr["kustomize"][key] for key in ("patches", "images") if key in pr.get("kustomize", {})}
        if not k:
            continue
        with tempfile.TemporaryDirectory() as work:
            pathlib.Path(work, "all.yaml").write_text(yaml.safe_dump_all(out))
            pathlib.Path(work, "kustomization.yaml").write_text(yaml.safe_dump({"resources": ["all.yaml"], **k}))
            out = docs_in(run(["kubectl", "kustomize", work]))
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["--list"]:
        print("\n".join(c["name"] for c in cases()))
    elif len(sys.argv) == 2:
        sys.stdout.write(render_case(sys.argv[1]))
    else:
        sys.exit(__doc__.split("\n\n")[1])
