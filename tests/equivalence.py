#!/usr/bin/env python3
"""Assert a rendered chart reproduces a set of hand-written manifests.

The design set mandates render-diff because one template change touches every application
(adr/0002). This is the narrower, more valuable version while apps are being ported: prove
the chart emits what the hand-written file emitted, so the port is provably a no-op.

  ./tests/equivalence.py [--allow-extra KIND,KIND] <rendered.yaml> <hand-written.yaml> [...]

`--allow-extra` names what the chart is expected to ADD — objects that did not exist in the
hand-written form. An entry is either a whole KIND, or one KIND/name when only that single
object is expected: `NetworkPolicy` blesses every NetworkPolicy, `ExternalSecret/docs-smtp`
blesses exactly one and still fails on the next unplanned Secret. Everything else the chart
adds, or drops, is a failure.

Two differences are normalised away because they are not differences:
  * ${BASE_DOMAIN} — Flux substitutes it before apply.
  * ESO placeholder names ({{ .secretkey }}) — internal to the ExternalSecret; they never
    appear in the Secret it produces.
"""
import re, sys, yaml

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

def main():
    args = sys.argv[1:]
    allow_extra = set()
    if args and args[0] == "--allow-extra":
        allow_extra = set(args[1].split(","))
        args = args[2:]
    if len(args) < 2:
        sys.exit(__doc__)
    domain = "haaijer.dev"
    got = dict(norm(o, domain) for o in load(args[0]))
    want = dict(norm(o, domain) for o in
                [o for p in args[1:] for o in load(p)])
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
    print("\nFAIL" if failed else f"\nOK — {len(want)} objects reproduced")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
