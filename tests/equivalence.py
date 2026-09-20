#!/usr/bin/env python3
"""Assert a rendered chart reproduces the hand-written manifests it replaced.

  ./tests/equivalence.py                                   the pre-port Docs manifests
  ./tests/equivalence.py [--allow-extra KIND,KIND] <rendered.yaml> <hand-written.yaml> [...]

The no-arg form is the check that made adopting Docs' live objects a no-op (14 adopted,
0 recreated), against the files frozen in tests/fixtures/pre-port/. When a chart change is
MEANT to alter one of those objects, drop the comparison and say so — do not re-freeze the
fixture from the new output (tests/fixtures/pre-port/README.md).

`--allow-extra` names what the chart is expected to ADD — objects that did not exist in the
hand-written form. An entry is either a whole KIND, or one KIND/name when only that single
object is expected: `NetworkPolicy` blesses every NetworkPolicy, `ExternalSecret/docs-smtp`
blesses exactly one and still fails on the next unplanned Secret. Everything else the chart
adds, or drops, is a failure.

Per kind, the fields that carry the contract are compared (`norm`), not the whole object:
an ExternalSecret's data/store/refresh, a route's hosts/paths/backends, a policy's buffer
and timeout. Kinds `norm` does not know compare by name only. This is a port check, not a
full diff — `render-diff.sh` is that.

Two differences are normalised away because they are not differences:
  * ${BASE_DOMAIN} — Flux substitutes it before apply.
  * ESO placeholder names ({{ .secretkey }}) — internal to the ExternalSecret; they never
    appear in the Secret it produces.
"""
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

FIX = render.ROOT / "tests" / "fixtures" / "pre-port"
# case -> (what the chart is expected to ADD, the frozen files). `docs-smtp`: the pre-port
# cluster could not send mail. NetworkPolicy: the hand-written set never had one (adr/0103).
PRE_PORT = {
    "docs-deps": ({"ExternalSecret/docs-smtp"}, ["docs-datastores.yaml", "docs-secrets.yaml"]),
    "docs-app": ({"NetworkPolicy"}, ["docs-routes.yaml"]),
}


def load(p):
    with open(p) as f:
        return [d for d in yaml.safe_load_all(f) if d]

def norm(o, domain):
    k = (o["kind"], o["metadata"]["name"])
    spec = o.get("spec", {})
    if o["kind"] == "ExternalSecret":
        data = {}
        for kk, vv in (spec.get("target", {}).get("template", {}).get("data") or {}).items():
            v = str(vv).replace("${BASE_DOMAIN}", domain)
            data[kk] = re.sub(r"\{\{\s*\.\w+\s*\}\}", "<GENERATED>", v)
        return k, {"data": data, "refresh": str(spec.get("refreshInterval")),
                   "store": (spec.get("secretStoreRef") or {}).get("name"),
                   "nrefs": len(spec.get("data") or spec.get("dataFrom") or [])}
    if o["kind"] == "GarageKey":
        st = spec["secretTemplate"]
        return k, {"secret": st["name"], "extra": st.get("additionalData"),
                   "keys": sorted(v for a, v in st.items() if a.endswith("Key"))}
    if o["kind"] == "GarageBucket":
        return k, {"alias": spec.get("globalAlias"), "quota": spec.get("quotas")}
    if o["kind"] == "HTTPRoute":
        rules = []
        for r in spec.get("rules", []):
            rules.append({
                "paths": sorted(m["path"]["value"] for m in r.get("matches", [])),
                "backends": sorted((b["name"], b["port"]) for b in r.get("backendRefs", [])),
            })
        parents = sorted((p.get("name"), p.get("namespace"), p.get("sectionName"))
                         for p in spec.get("parentRefs", []))
        return k, {"hosts": [h.replace("${BASE_DOMAIN}", domain) for h in spec.get("hostnames", [])],
                   "parents": parents, "rules": rules}
    if o["kind"] == "BackendTrafficPolicy":
        return k, {"targets": sorted((t.get("kind"), t.get("name")) for t in spec.get("targetRefs", [])),
                   "buffer": (spec.get("requestBuffer") or {}).get("limit"),
                   "timeout": spec.get("timeout", {}).get("http")}
    return k, {}

def compare(got_docs, want_docs, allow_extra, domain="haaijer.dev") -> bool:
    got = dict(norm(o, domain) for o in got_docs)
    want = dict(norm(o, domain) for o in want_docs)
    failed = False
    for k in sorted(set(got) | set(want)):
        if k not in got:
            print(f"MISSING: {k[0]} {k[1]}"); failed = True
        elif k not in want:
            if k[0] in allow_extra or f"{k[0]}/{k[1]}" in allow_extra:
                print(f"ADDED  : {k[0]:15} {k[1]}")
            else:
                print(f"EXTRA  : {k[0]:15} {k[1]}"); failed = True
        elif got[k] == want[k]:
            print(f"MATCH  : {k[0]:15} {k[1]}")
        else:
            failed = True
            print(f"DIFFER : {k[0]:15} {k[1]}")
            for f in sorted(set(got[k]) | set(want[k])):
                if got[k].get(f) != want[k].get(f):
                    print(f"     {f}:\n       chart={got[k].get(f)!r}\n       hand ={want[k].get(f)!r}")
    print("FAIL" if failed else f"OK — {len(want)} objects reproduced")
    return not failed


def main() -> int:
    args = sys.argv[1:]
    if args:
        allow_extra = set()
        if args[0] == "--allow-extra":
            allow_extra, args = set(args[1].split(",")), args[2:]
        if len(args) < 2:
            sys.exit(__doc__)
        return not compare(load(args[0]), [o for p in args[1:] for o in load(p)], allow_extra)
    ok = True
    for case_name, (allow, files) in PRE_PORT.items():
        print(f"== {case_name} vs the hand-written {', '.join(files)}")
        ok &= compare(render.docs_in(render.render_case(case_name)),
                      [o for f in files for o in load(FIX / f)], allow)
        print()
    print("OK — the charts still reproduce the pre-port manifests" if ok
          else "FAIL — the charts no longer reproduce what the cluster had before the port.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
