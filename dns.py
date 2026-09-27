#!/usr/bin/env python3
"""
Print every DNS record a cluster needs, read out of the config that will use them.

    ./dns.py                              every cluster case in tests/cases/
    ./dns.py prod                         one of them
    ./dns.py ../cluster-prod/cluster.yaml an organisation's own file — values or HelmRelease
    ./dns.py prod --check                 and resolve each name, to see what is already true
    ./dns.py prod --zone                  BIND-format records, nothing else

What comes out is every hostname this Gateway serves: the SAN list on the Certificate the
Gateway actually references, plus every HTTPRoute hostname — including the ones
`platform-app` renders from `routes[].host`, which exist nowhere in this repo as a literal
string.

WHY THIS IS WORTH A SCRIPT. `platform/gateway/certificate.yaml` carries the rule: a
hostname may be listed there only once its DNS resolves to the Gateway, because Let's
Encrypt fails the WHOLE certificate if any single SAN fails validation. One mispointed
record therefore takes down TLS for every application, not for one. So the SAN list is a
list of records that must already exist, and this prints it in the order you need it: DNS
first, release second.

It also cross-checks the two sources against each other. A route hostname with no SAN
terminates TLS with no certificate for that SNI, which is a handshake failure and not a
404 — the kind of thing that looks like a routing bug for an hour.

Rendered through `tests/render.py`, the way the cluster does it: the control plane from
the cluster's values, then every layer it emits with its size profile and substitutions.
A hostname in a file no kustomization lists does not appear, because it would not be
served either.
"""
import argparse
import atexit
import pathlib
import re
import socket
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "tests"))
import render  # noqa: E402

ROOT = render.ROOT


def values_file(path):
    """A values file as it is; an organisation's cluster.yaml by its HelmRelease's values."""
    docs = [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]
    release = next((d for d in docs if d.get("kind") == "HelmRelease"), None)
    if release is None:
        return path
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(release["spec"].get("values") or {}, f)
    atexit.register(pathlib.Path(f.name).unlink)
    return pathlib.Path(f.name)


def gateway_sans(docs):
    """
    SAN list of the certificate the Gateway actually terminates with.

    Found through the Gateway's own certificateRefs rather than by picking Certificates
    out of the tree: `platform/opensearch/certificate.yaml` is also a Certificate, and its
    dnsNames are in-cluster service names that belong in no zone file.
    """
    refs, sans = set(), {}
    for doc in docs:
        if doc.get("kind") != "Gateway":
            continue
        ns = doc.get("metadata", {}).get("namespace")
        for listener in doc.get("spec", {}).get("listeners") or []:
            for ref in (listener.get("tls") or {}).get("certificateRefs") or []:
                refs.add((ref.get("namespace", ns), ref.get("name")))
    for doc in docs:
        if doc.get("kind") != "Certificate":
            continue
        meta, spec = doc.get("metadata", {}), doc.get("spec", {})
        if (meta.get("namespace"), spec.get("secretName")) in refs:
            for name in spec.get("dnsNames") or []:
                sans.setdefault(name, f"{meta.get('namespace')}/{meta.get('name')}")
    return sans


def served(docs, base_domain):
    """hostname -> the objects that answer on it."""
    hosts = {}

    def add(hostname, owner):
        if hostname:
            hosts.setdefault(hostname, []).append(owner)

    for doc in docs:
        kind = doc.get("kind")
        meta = doc.get("metadata", {}) or {}
        owner = f"{meta.get('namespace', '-')}/{meta.get('name', '?')}"
        spec = doc.get("spec", {}) or {}

        if kind == "HTTPRoute":
            for hostname in spec.get("hostnames") or []:
                add(hostname, owner)

        # platform-app renders one HTTPRoute per entry in `routes`, and `host` is the
        # short form joined to baseDomain — so these hostnames exist as a literal string
        # in neither this repo nor the chart. This is the half a grep would miss.
        elif kind == "HelmRelease":
            values = spec.get("values") or {}
            base = values.get("baseDomain") or base_domain
            for route in values.get("routes") or []:
                if route.get("hostname"):
                    add(route["hostname"], owner)
                elif route.get("host") and base:
                    add(f"{route['host']}.{base}", owner)
            # TURN's hostname is on no HTTPRoute and no certificate: a UDPRoute on the same
            # Gateway (adr/0113), inside platform-app's `extraObjects`.
            if base and any(o.get("kind") == "UDPRoute" and "turn" in o["metadata"]["name"]
                            for o in values.get("extraObjects") or []):
                add(f"turn.{base}", f"{owner} (TURN/UDP 3478)")

        # The browser-facing issuer. It is not a route, but it must be the same name the
        # route serves or every OIDC redirect lands somewhere that does not exist.
        elif kind == "Keycloak":
            url = ((spec.get("hostname") or {}).get("hostname")) or ""
            match = re.match(r"https?://([^/:]+)", str(url))
            if match:
                add(match.group(1), owner + " (issuer)")

    return hosts


def resolve(hostname):
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        return None, exc.strerror or str(exc)
    return sorted({info[4][0] for info in infos}), None


def report(path, args):
    layers = render.cluster(values_file(path))
    variables = next(d["data"] for d in layers["control-plane"] if d["kind"] == "ConfigMap")
    base_domain = variables.get("BASE_DOMAIN", "")
    gateway_ip = variables.get("GATEWAY_IP", "")
    docs = [d for name, ds in layers.items() if name != "control-plane" for d in ds]

    sans = gateway_sans(docs)
    hosts = served(docs, base_domain)
    records = sorted(set(sans) | set(hosts))

    if args.zone:
        for name in records:
            print(f"{name}.\t300\tIN\tA\t{gateway_ip}")
        return 0

    print(f"== {path.stem.removeprefix('cluster-')} — base domain {base_domain or '(unset)'}, Gateway {gateway_ip or '(unset)'}")
    print()
    print(f"   {len(records)} A records, all to {gateway_ip}:")
    print()
    for name in records:
        serves = ", ".join(sorted(set(hosts.get(name, [])))) or "no route — SAN only"
        print(f"   {name:<34} A  {gateway_ip:<16} {serves}")
    if base_domain and all(n.endswith("." + base_domain) for n in records):
        print()
        print(f"   Or one wildcard instead of the {len(records)}:  "
              f"*.{base_domain}  A  {gateway_ip}")

    print()
    print("   Order and caveats:")
    print("   - Create every record above BEFORE the first release. cert-manager solves")
    print("     HTTP-01 through this Gateway, so :80 and :443 must reach it from the")
    print("     internet, and Let's Encrypt fails the WHOLE certificate if one SAN fails")
    print("     validation — one bad record is an outage for every application, not one.")
    print("   - The certificate's SAN list is derived from the apps this cluster enables, so")
    print("     turning one on adds its record here; create it BEFORE enabling the app.")

    problems = []
    for name in sorted(set(hosts) - set(sans)):
        if name.startswith("turn."):
            continue                      # UDP: no TLS to hand-shake
        problems.append(f"{name} is routed but is not on the certificate — TLS handshake "
                        f"fails for it, which does not look like a routing bug")
    for name in sorted(set(sans) - set(hosts)):
        problems.append(f"{name} is on the certificate but nothing routes it — the record "
                        f"is still required, or drop the host from the app table")

    if args.check:
        if not gateway_ip:
            problems.append("no gateway.ip in the values — nothing to check against")
        for name in records:
            addresses, error = resolve(name)
            if error:
                problems.append(f"{name} does not resolve ({error})")
            elif gateway_ip and gateway_ip not in addresses:
                problems.append(f"{name} resolves to {', '.join(addresses)}, not {gateway_ip}")

    print()
    if problems:
        print(f"   {len(problems)} thing(s) to fix:")
        for problem in problems:
            print(f"   ! {problem}")
    else:
        print("   No problems found" + ("" if args.check else " (--check also resolves them)"))
    print()
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(
        description="Print the DNS records a cluster needs, read out of its own config.")
    parser.add_argument("cluster", nargs="?",
                        help="a cluster case name (prod, demo, …) or a path to a values / cluster.yaml "
                             "file; default every cluster case")
    parser.add_argument("--check", action="store_true",
                        help="resolve each name and report what disagrees")
    parser.add_argument("--zone", action="store_true",
                        help="BIND-format records only, for pasting into a zone file")
    args = parser.parse_args()

    files = render.clusters()
    if args.cluster:
        given = pathlib.Path(args.cluster)
        files = [given] if given.is_file() else [f for f in files if f.stem == f"cluster-{args.cluster}"]
        if not files:
            parser.error(f"no cluster case {args.cluster!r} in tests/cases/index.yaml and no such file")

    return max(report(f, args) for f in files)


if __name__ == "__main__":
    sys.exit(main())
