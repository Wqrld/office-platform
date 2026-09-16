#!/usr/bin/env python3
"""
Print every DNS record a cluster needs, read out of the config that will use them.

    ./dns.py                    every cluster
    ./dns.py prod               one cluster
    ./dns.py prod --check       and resolve each name, to see what is already true
    ./dns.py prod --zone        BIND-format records, nothing else

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

Rendered through `tests/build.sh` when `flux` is on PATH, so size-profile overlays and the
explicit resource lists are respected. Without it, the source tree is scanned instead and
the difference is stated in the output — that fallback can name a hostname whose file is
not in any kustomization.
"""
import argparse
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent

# Scanned only in the fallback: vendored upstream (no hostnames of ours) and the routes
# for services that still live behind the legacy ingress — deferred/ is deliberately in
# no kustomization, and a rendered build would not show it either.
SKIP = {"vendor", "deferred", "__pycache__"}


def cluster_vars(cluster_dir):
    """The ConfigMap Flux substitutes from, read from where it is defined."""
    for path in sorted(cluster_dir.glob("*.yaml")):
        for doc in load(path.read_text()):
            if doc.get("kind") == "ConfigMap" and doc.get("metadata", {}).get("name") == "cluster-vars":
                return doc.get("data") or {}
    return {}


def load(text):
    """Parse a multi-doc YAML string, skipping documents that are not objects."""
    try:
        docs = yaml.safe_load_all(text)
        return [d for d in docs if isinstance(d, dict)]
    except yaml.YAMLError:
        return []


def substitute(text, variables):
    """What postBuild does. Keycloak's own $${NAME} placeholders survive, as they must."""
    for key, value in variables.items():
        text = text.replace("${%s}" % key, str(value))
    return text


def rendered(cluster_dir, variables):
    """The layers as Flux would apply them. Returns None if `flux` cannot render them."""
    if not shutil.which("flux"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [str(ROOT / "tests" / "build.sh"), tmp],
            capture_output=True, text=True,
        )
        out = pathlib.Path(tmp) / cluster_dir.name
        if not out.is_dir():
            sys.stderr.write(proc.stdout + proc.stderr)
            return None
        docs = []
        for path in sorted(out.glob("*.yaml")):
            docs += load(path.read_text())
        return docs


def scanned(variables):
    """Fallback: the source tree, substituted by hand."""
    docs = []
    for base in ("platform", "apps"):
        for path in sorted((ROOT / base).rglob("*.yaml")):
            if SKIP & set(path.relative_to(ROOT).parts):
                continue
            docs += load(substitute(path.read_text(), variables))
    return docs


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


def report(cluster_dir, args):
    variables = cluster_vars(cluster_dir)
    base_domain = variables.get("BASE_DOMAIN", "")
    gateway_ip = variables.get("GATEWAY_IP", "")

    docs = rendered(cluster_dir, variables)
    fallback = docs is None
    if fallback:
        docs = scanned(variables)

    sans = gateway_sans(docs)
    hosts = served(docs, base_domain)
    records = sorted(set(sans) | set(hosts))
    # Records that must NOT point at the Gateway: LiveKit's media address. The TURN
    # hostname is neither routed nor on the certificate (apps/livekit/README.md), so it is
    # stated here from the variable rather than found in the render.
    off_gateway = {f"turn.{base_domain}": variables["LIVEKIT_IP"]} if variables.get("LIVEKIT_IP") else {}

    if args.zone:
        for name in records:
            print(f"{name}.\t300\tIN\tA\t{gateway_ip}")
        for name, ip in off_gateway.items():
            print(f"{name}.\t300\tIN\tA\t{ip}")
        return 0

    print(f"== clusters/{cluster_dir.name} — base domain {base_domain or '(unset)'}, "
          f"Gateway {gateway_ip or '(unset)'}")
    if fallback:
        print("   (read from the source tree, not a rendered build — install `flux` for the")
        print("    exact set: a file that is in no kustomization can still be listed here)")
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
    for name, ip in off_gateway.items():
        print()
        print(f"   And NOT to the Gateway — an explicit record that must beat the wildcard:")
        print(f"   {name:<34} A  {ip:<16} LiveKit TURN/media (apps/livekit)")

    print()
    print("   Order and caveats:")
    print("   - Create every record above BEFORE the first release. cert-manager solves")
    print("     HTTP-01 through this Gateway, so :80 and :443 must reach it from the")
    print("     internet, and Let's Encrypt fails the WHOLE certificate if one SAN fails")
    print("     validation — one bad record is an outage for every application, not one.")
    print("   - Adding an application later is one dnsName in")
    print("     platform/gateway/certificate.yaml, added only once its record resolves.")

    problems = []
    for name in sorted(set(hosts) - set(sans)):
        problems.append(f"{name} is routed but is not on the certificate — TLS handshake "
                        f"fails for it, which does not look like a routing bug")
    for name in sorted(set(sans) - set(hosts)):
        problems.append(f"{name} is on the certificate but nothing routes it — the record "
                        f"is still required, or drop the SAN")

    if args.check:
        if not gateway_ip:
            problems.append("no GATEWAY_IP in vars.yaml — nothing to check against")
        for name in records:
            addresses, error = resolve(name)
            if error:
                problems.append(f"{name} does not resolve ({error})")
            elif gateway_ip and gateway_ip not in addresses:
                problems.append(f"{name} resolves to {', '.join(addresses)}, not {gateway_ip}")
        for name, ip in off_gateway.items():
            addresses, error = resolve(name)
            if error:
                problems.append(f"{name} does not resolve ({error})")
            elif ip not in addresses:
                problems.append(f"{name} resolves to {', '.join(addresses)}, not {ip}")

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
    parser.add_argument("cluster", nargs="?", help="one cluster; default every cluster")
    parser.add_argument("--check", action="store_true",
                        help="resolve each name and report what disagrees")
    parser.add_argument("--zone", action="store_true",
                        help="BIND-format records only, for pasting into a zone file")
    args = parser.parse_args()

    dirs = sorted(d for d in (ROOT / "clusters").iterdir() if (d / "vars.yaml").is_file())
    if args.cluster:
        dirs = [d for d in dirs if d.name == args.cluster]
        if not dirs:
            parser.error(f"no cluster {args.cluster!r} under clusters/")

    return max(report(d, args) for d in dirs)


if __name__ == "__main__":
    sys.exit(main())
