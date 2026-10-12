#!/usr/bin/env python3
"""Will every pod start?

    ./tests/startup.py [app ...]      default: every app under apps/

Every app at `medium`, as helm-controller applies it, and two assertions per pod template.
nonroot: a container with `runAsNonRoot` and no `runAsUser` needs an image whose config
names a numeric, non-zero user, or the kubelet refuses it — read from each pinned image's
registry, cached in .charts/images.json. waits: every Secret and ConfigMap a release's pod
needs comes from the release itself, a plain object in the layer, or a release in its
`dependsOn` chain; anything else is a wait that can deadlock. See `AGENTS.md` (Checks).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

CACHE = render.CACHE / "images.json"
ARCH = "amd64"                     # the nodes'; a multi-arch image is judged by this one
INDEX = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
MANIFEST = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")


# ---------------------------------------------------------------- registry

def _get(url: str, accept: str) -> bytes:
    """GET from a registry, answering its Bearer challenge anonymously if it makes one."""
    def req(token=None):
        h = {"Accept": accept} | ({"Authorization": f"Bearer {token}"} if token else {})
        return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read()
    try:
        return req()
    except urllib.error.HTTPError as e:
        if e.code != 401 or "bearer" not in e.headers.get("WWW-Authenticate", "").lower():
            raise
        p = dict(re.findall(r'(\w+)="([^"]*)"', e.headers["WWW-Authenticate"]))
        q = urllib.parse.urlencode({k: p[k] for k in ("service", "scope") if k in p})
        tok = json.loads(urllib.request.urlopen(f"{p['realm']}?{q}", timeout=30).read())
        return req(tok.get("token") or tok.get("access_token"))


def _split(ref: str) -> tuple[str, str, str]:
    """`ghcr.io/a/b:1.0`, `nginx:1.27`, `x@sha256:…` -> (registry host, repository, tag or digest)."""
    name, _, digest = ref.partition("@")
    host, _, rest = name.partition("/")
    if not rest or ("." not in host and ":" not in host and host != "localhost"):
        host, rest = "docker.io", name
    if host == "docker.io":
        host, rest = "registry-1.docker.io", rest if "/" in rest.split(":")[0] else f"library/{rest}"
    repo, _, tag = rest.rpartition(":") if ":" in rest.rsplit("/", 1)[-1] else (rest, "", "latest")
    return host, repo, digest or tag


def image_user(ref: str) -> str:
    """The `User` an image's config declares, "" for none — which is root."""
    host, repo, ref_ = _split(ref)
    base = f"https://{host}/v2/{repo}"
    m = json.loads(_get(f"{base}/manifests/{ref_}", ", ".join(INDEX + MANIFEST)))
    if m.get("mediaType") in INDEX or "manifests" in m:
        pick = next((x for x in m["manifests"] if x.get("platform", {}).get("os") == "linux"
                     and x["platform"].get("architecture") == ARCH), None)
        if pick is None:
            raise RuntimeError(f"no linux/{ARCH} image in the index")
        m = json.loads(_get(f"{base}/manifests/{pick['digest']}", ", ".join(MANIFEST)))
    cfg = json.loads(_get(f"{base}/blobs/{m['config']['digest']}", "*/*"))
    return (cfg.get("config") or {}).get("User") or ""


# ---------------------------------------------------------------- pods

def containers(pod: dict):
    return (pod.get("initContainers") or []) + (pod.get("containers") or [])


def needs(pod: dict) -> set[tuple[str, str]]:
    """(kind, name) of every Secret and ConfigMap the pod cannot start without."""
    out = set()
    for v in pod.get("volumes") or []:
        if (s := v.get("secret")) and not s.get("optional"):
            out.add(("Secret", s["secretName"]))
        if (c := v.get("configMap")) and not c.get("optional"):
            out.add(("ConfigMap", c["name"]))
        for src in (v.get("projected") or {}).get("sources") or []:
            for kind, key in (("Secret", "secret"), ("ConfigMap", "configMap")):
                if (r := src.get(key)) and not r.get("optional"):
                    out.add((kind, r["name"]))
    for c in containers(pod):
        for e in c.get("envFrom") or []:
            for kind, key in (("Secret", "secretRef"), ("ConfigMap", "configMapRef")):
                if (r := e.get(key)) and not r.get("optional"):
                    out.add((kind, r["name"]))
        for e in c.get("env") or []:
            for kind, key in (("Secret", "secretKeyRef"), ("ConfigMap", "configMapKeyRef")):
                if (r := (e.get("valueFrom") or {}).get(key)) and not r.get("optional"):
                    out.add((kind, r["name"]))
    return out


def produces(d: dict) -> set[tuple[str, str]]:
    """What an object brings into existence, directly or through its controller."""
    k, n = d.get("kind"), d["metadata"]["name"]
    if k in ("Secret", "ConfigMap"):
        return {(k, n)}
    if k == "ExternalSecret":
        return {("Secret", (d["spec"].get("target") or {}).get("name") or n)}
    if k == "Certificate":
        return {("Secret", d["spec"]["secretName"])}
    if k == "GarageKey":
        return {("Secret", (d["spec"].get("secretTemplate") or {}).get("name") or n)}
    if k == "Role":
        # A Job that creates its Secret at run time (the chart's jwt-keys job) is not in the
        # manifest: its Role says so. A Role allowed to `create` secrets produces the ones it
        # names with `get` — the Job is the only thing that can create them.
        rules = d.get("rules") or []
        if any("secrets" in r.get("resources", []) and "create" in r.get("verbs", []) for r in rules):
            return {("Secret", name) for r in rules
                    if "secrets" in r.get("resources", []) and "get" in r.get("verbs", [])
                    for name in r.get("resourceNames", [])}
    return set()


# ---------------------------------------------------------------- checks

def check_nonroot(obj: dict, pod: dict, users: dict) -> list[str]:
    out = []
    psc = pod.get("securityContext") or {}
    for c in containers(pod):
        sc = c.get("securityContext") or {}
        if not sc.get("runAsNonRoot", psc.get("runAsNonRoot")):
            continue
        where = f"{obj['kind']}/{obj['metadata']['name']} container {c['name']}"
        uid = sc.get("runAsUser", psc.get("runAsUser"))
        if uid is not None:
            if uid == 0:
                out.append(f"{where}: runAsNonRoot with runAsUser 0")
            continue
        if c["image"] not in users:
            try:
                users[c["image"]] = image_user(c["image"])
            except Exception as e:  # noqa: BLE001 — any failure to read is a failure to verify
                out.append(f"{where}: cannot read {c['image']}'s config ({e})")
                continue
        user = users[c["image"]].split(":")[0]
        if not user.isdigit() or int(user) == 0:
            out.append(f"{where}: runAsNonRoot, no runAsUser, and {c['image']} runs as "
                       f"{user or 'root (no USER)'!r} — the kubelet refuses it; set runAsUser")
    return out


def closure(name: str, deps: dict[str, list[str]]) -> set[str]:
    seen, todo = set(), list(deps.get(name, []))
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += deps.get(n, [])
    return seen


def check_app(app: str, srcs: dict, users: dict) -> list[str]:
    docs = render.apps("medium", [app])
    rels = [d for d in docs if d.get("kind") == "HelmRelease"]
    plain = [d for d in docs if d.get("kind") not in {"HelmRelease", "Kustomization"}]
    deps = {r["metadata"]["name"]: [x["name"] for x in r["spec"].get("dependsOn") or []] for r in rels}

    made: dict[str, list[dict]] = {"": plain}          # "" is the layer's own plain objects
    problems = []
    for r, out, err in render.releases(docs, srcs):
        if err:
            problems.append(f"{app}: {err}")
        else:
            made[r["metadata"]["name"]] = out
    producers: dict[tuple[str, str], set[str]] = {}
    for owner, objs in made.items():
        for d in objs:
            for p in produces(d):
                producers.setdefault(p, set()).add(owner)

    n = 0
    for owner, objs in made.items():
        # A plain object is waited on by nothing but its layer, and no release waits on the
        # layer: it starts whenever its inputs appear. A release is waited on by Helm: Helm
        # waits for the pod, the pod for the Secret, and the Secret's release for Helm.
        allowed = set(made) if not owner else {"", owner} | closure(owner, deps)
        for obj, pod, _ in render.pod_specs(objs):
            n += 1
            problems += [f"{app}: {x}" for x in check_nonroot(obj, pod, users)]
            for need in sorted(needs(pod)):
                src = producers.get(need)
                where = f"{obj['kind']}/{obj['metadata']['name']} ({owner or 'plain'})"
                if not src:
                    problems.append(f"{app}: {where} needs {need[0]}/{need[1]}, which nothing in the layer creates")
                elif not src & allowed:
                    problems.append(f"{app}: {where} needs {need[0]}/{need[1]}, made only by "
                                    f"{', '.join(sorted(src))} — not in {owner}'s dependsOn, so its wait "
                                    f"can deadlock; make it a plain object or a dependency")
    print(f"   {app:12} {n} pod templates")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apps", nargs="*", help="default: every app under apps/")
    args = ap.parse_args()
    users = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    srcs = render.sources()
    problems: list[str] = []
    for app in args.apps or render.APPS:
        problems += check_app(app, srcs, users)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(users, indent=1, sort_keys=True))
    return render.report(problems, "every non-root container can run as its image's user, and nothing "
                                   "waits on what waits on it", "problem(s): pods that will not start")


if __name__ == "__main__":
    sys.exit(main())
