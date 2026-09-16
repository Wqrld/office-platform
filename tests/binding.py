#!/usr/bin/env python3
"""The binding check — does the surround still attach to what the upstream chart creates?

    ./tests/binding.py [app ...]        default: every app under apps/

This is the test 10-verification.md calls "the test this architecture needs and a
chart-per-app architecture did not", and it is the one that pays for adr/0012.

The gap it closes: our surround SELECTS INTO workloads that a different release created.
If an upstream bump renames a Service or a component label, *our* rendered output does not
change at all — so the golden files match, render-diff is clean, kubeconform passes, and
the routes point at nothing. Every other check in this repo is green while the site is
down.

So this one renders the upstream release and the surround release TOGETHER and asserts:

  * every route backendRef resolves to a Service that exists, on the port it declares;
  * the upstream release emits none of the kinds the surround owns — a PDB, ServiceMonitor,
    HPA or NetworkPolicy from both releases means two objects selecting the same pods, and
    two PDBs on one workload is a drain that hangs;
  * the upstream release emits no Ingress, because we route with Gateway API and an Ingress
    left enabled is a second, unauthenticated way in.

Upstream charts come from the pins the control plane renders (charts/control-plane/templates/
sources.yaml) — a git tag for La Suite (adr/0104) or a chart repository for Collabora — so
this checks the version that is actually deployed, not whatever is current.

Needs network: it fetches the pinned upstream charts. That makes it a PR check, not a
pre-commit hook.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

HERE = render.ROOT
PROD = render.CASES / "cluster-prod.yaml"

# Kinds the surround owns. Two objects of these selecting the same pods is the failure.
SURROUND_OWNED = {"PodDisruptionBudget", "ServiceMonitor", "HorizontalPodAutoscaler", "NetworkPolicy"}


def load_all(path: pathlib.Path) -> list[dict]:
    with open(path) as f:
        return [d for d in yaml.safe_load_all(f) if d]


def docs_in(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def sources() -> dict[str, dict]:
    """name -> source object, as the control plane renders them for prod."""
    return {d["metadata"]["name"]: d for d in render.control_plane(PROD)
            if d["kind"] in {"GitRepository", "HelmRepository", "OCIRepository"}}


def variables() -> dict[str, str]:
    """prod's cluster-vars, as the control plane renders them."""
    return next(d["data"] for d in render.control_plane(PROD)
                if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cluster-vars")


substitute = render.substitute


def helm_template(chart: str, release: str, ns: str, values: dict, extra: list[str] | None = None) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(values, f)
        vf = f.name
    cmd = ["helm", "template", release, chart, "--namespace", ns,
           "--kube-version", "1.34.2", "--values", vf, *(extra or [])]
    out = subprocess.run(cmd, capture_output=True, text=True)
    pathlib.Path(vf).unlink()
    if out.returncode != 0:
        raise RuntimeError(f"helm template failed for {release}:\n{out.stderr}")
    return docs_in(out.stdout)


def git_checkout(url: str, ref: dict, dest: pathlib.Path) -> None:
    """Shallow-checkout a GitRepository ref, which may be a tag OR a bare commit.

    `--branch` takes a branch or a tag and rejects a SHA, so a commit pin needs the
    fetch-then-checkout form. Find is pinned that way because upstream has never cut a
    release — see apps/find/README.md.
    """
    if tag := ref.get("tag"):
        subprocess.run(["git", "clone", "--depth", "1", "--branch", tag, "--quiet", url, str(dest)],
                       check=True, capture_output=True, text=True)
        return

    commit = ref["commit"]
    dest.mkdir(parents=True)
    for cmd in (["git", "init", "--quiet"],
                ["git", "remote", "add", "origin", url],
                ["git", "fetch", "--depth", "1", "--quiet", "origin", commit],
                ["git", "checkout", "--quiet", "FETCH_HEAD"]):
        subprocess.run(cmd, cwd=dest, check=True, capture_output=True, text=True)


def fetch_upstream(rel: dict, srcs: dict, work: pathlib.Path) -> str | None:
    """Return a local chart path for a HelmRelease's chart, fetching the pinned version."""
    spec = rel["spec"]
    if "chart" not in spec:
        return None                       # chartRef — one of ours, rendered from the repo
    cs = spec["chart"]["spec"]
    src = srcs.get(cs["sourceRef"]["name"])
    if src is None:
        raise RuntimeError(f"{rel['metadata']['name']}: no source {cs['sourceRef']['name']}")

    if src["kind"] == "GitRepository":
        ref = src["spec"]["ref"]
        dest = work / src["metadata"]["name"]
        if not dest.exists():
            git_checkout(src["spec"]["url"], ref, dest)
        return str(dest / cs["chart"])

    if src["kind"] == "HelmRepository":
        dest = work / f"repo-{src['metadata']['name']}" / cs["version"]
        # `helm pull --untar` refuses to overwrite, so a second caller for the same chart
        # fails with "file already exists" — which reads like a broken pin rather than a
        # cache hit. The version is in the path because the cache outlives one release.
        if not (dest / cs["chart"]).is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            out = subprocess.run(
                ["helm", "pull", cs["chart"], "--repo", src["spec"]["url"],
                 "--version", cs["version"], "--untar", "--untardir", str(dest)],
                capture_output=True, text=True,
            )
            if out.returncode != 0:
                raise RuntimeError(
                    f"helm pull {cs['chart']} {cs['version']} from {src['spec']['url']}: {out.stderr.strip()}")
        return str(dest / cs["chart"])

    raise RuntimeError(f"unsupported source kind {src['kind']}")


def local_chart(rel: dict) -> str | None:
    """Our own charts, rendered from charts/ rather than pulled from the registry."""
    ref = rel["spec"].get("chartRef")
    if not ref:
        return None
    p = HERE / "charts" / ref["name"]
    return str(p) if p.is_dir() else None


def check_app(app_dir: pathlib.Path, srcs: dict, work: pathlib.Path, variables: dict) -> list[str]:
    problems: list[str] = []
    app = app_dir.name

    releases: list[dict] = []
    for f in sorted(app_dir.glob("*.yaml")):
        for d in load_all(f):
            if d.get("kind") == "HelmRelease":
                releases.append(d)

    upstream: list[dict] = []
    surround: list[dict] = []
    # Objects the app dir declares directly — Docs' hand-written media proxy is one, until
    # it moves onto platform-app's mediaProxy (adr/0109).
    plain: list[dict] = []
    for f in sorted(app_dir.glob("*.yaml")):
        for d in load_all(f):
            if d.get("kind") not in {"HelmRelease", "Kustomization"}:
                plain.append(d)

    for rel in releases:
        name = rel["metadata"]["name"]
        ns = rel["metadata"]["namespace"]
        values = substitute(rel["spec"].get("values") or {}, variables)

        chart = local_chart(rel)
        if chart:
            if not (pathlib.Path(chart) / "charts").exists():
                subprocess.run(["helm", "dependency", "build", chart],
                               check=True, capture_output=True, text=True)
            surround += helm_template(chart, name, ns, values)
            continue

        if rel["spec"].get("chartRef"):
            # A chartRef we could not resolve locally. Saying "no chart" here would be a
            # lie that sends the reader looking in the wrong repo.
            problems.append(
                f"{app}/{name}: chartRef {rel['spec']['chartRef']['name']!r} did not resolve to a "
                f"chart under charts/"
            )
            continue

        chart = fetch_upstream(rel, srcs, work)
        if chart is None:
            problems.append(f"{app}/{name}: neither chart nor chartRef")
            continue
        try:
            upstream += helm_template(chart, name, ns, values)
        except RuntimeError as e:
            problems.append(f"{app}/{name}: {e}")

    # --- every backendRef must resolve -----------------------------------------------------
    services: dict[str, set[int]] = {}
    for d in upstream + surround + plain:
        if d.get("kind") == "Service":
            ports = {p["port"] for p in d["spec"].get("ports", []) if "port" in p}
            services.setdefault(d["metadata"]["name"], set()).update(ports)

    for d in surround:
        if d.get("kind") != "HTTPRoute":
            continue
        route = d["metadata"]["name"]
        for rule in d["spec"].get("rules", []):
            for b in rule.get("backendRefs", []):
                n, p = b["name"], b.get("port")
                if n not in services:
                    problems.append(
                        f"{app}: HTTPRoute/{route} routes to Service {n!r}, which no release creates"
                    )
                elif p is not None and p not in services[n]:
                    have = sorted(services[n]) or "no ports at all"
                    problems.append(
                        f"{app}: HTTPRoute/{route} routes to {n}:{p}, but that Service exposes {have}"
                    )

    # --- the upstream release must not emit what the surround owns -------------------------
    for d in upstream:
        k = d.get("kind")
        if k in SURROUND_OWNED:
            problems.append(
                f"{app}: the upstream release emits {k}/{d['metadata']['name']} — "
                f"the surround owns that kind, and two of them selecting the same pods is a drain that hangs"
            )
        if k == "Ingress":
            problems.append(
                f"{app}: the upstream release emits Ingress/{d['metadata']['name']} — "
                f"routing is Gateway API here, and a live Ingress is a second way in"
            )

    counts = f"{len(upstream)} upstream + {len(surround)} surround + {len(plain)} plain objects"
    print(f"   {app:12} {counts}, {len(services)} services")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("apps", nargs="*")
    args = ap.parse_args()

    srcs = sources()
    vars_ = variables()
    work = pathlib.Path(tempfile.mkdtemp(prefix="binding-"))
    problems: list[str] = []

    try:
        dirs = [HERE / "apps" / a for a in args.apps] if args.apps else \
               sorted(p for p in (HERE / "apps").iterdir() if p.is_dir() and (p / "release.yaml").exists())
        print("== rendering upstream releases at their pinned versions")
        for d in dirs:
            problems += check_app(d, srcs, work, vars_)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print()
    if problems:
        print("== binding failures")
        for p in problems:
            print(f"   {p}")
        print(f"\nFAIL — {len(problems)} binding problem(s)")
        return 1
    print("OK — every route resolves, and no upstream release emits a surround-owned kind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
