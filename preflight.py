#!/usr/bin/env python3
"""Is this cluster ready for this cluster.yaml? Run before `kubectl apply -f cluster.yaml`.

    ./preflight.py cluster.yaml        the file install.sh writes, or a bare values file

Checks against the live cluster what the platform assumes and cannot install itself —
StorageClass, GatewayClass, cert-manager with Gateway API, a LoadBalancer, DNS (`dns.py
--check`), SMTP, the Hugging Face token Meet needs, a Prometheus operator that suits
`monitoring.mode`, the kubelet's graceful shutdown — and skips what `cluster.*.install`
says the platform installs. SMTP_HOST/SMTP_PORT and HF_TOKEN come from the environment, as
install.sh sets them. Exit 1 on any FAIL. See `docs/install.md`.
"""
import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tests"))
import render  # noqa: E402

failed = False


def say(status, what, detail=""):
    global failed
    failed |= status == "FAIL"
    print(f"{status:4} {what}" + (f" — {detail}" if detail else ""))


def kubectl(*args, check=False, input=None):
    out = subprocess.run(["kubectl", *args], capture_output=True, text=True, input=input)
    if check and out.returncode:
        raise RuntimeError(out.stderr.strip())
    return out.stdout


def kget(*args):
    out = kubectl("get", *args, "-o", "json")
    return json.loads(out) if out else {}


def check_flux_operator():
    if kget("deploy", "-n", "flux-system", "--ignore-not-found", "flux-operator"):
        say("PASS", "flux-operator")
    else:
        say("WARN", "flux-operator", "not installed; install.sh does that next")


def check_storage(name):
    if kget("sc", "--ignore-not-found", name):
        say("PASS", f"StorageClass {name}")
    else:
        say("FAIL", f"StorageClass {name}", "does not exist; set storageClass to one that does")


def check_gateway(c):
    if c["install"]:
        return say("SKIP", "GatewayClass", "the platform installs Envoy Gateway")
    try:
        gc = kget("gatewayclass", c["className"])
    except (json.JSONDecodeError, RuntimeError):
        gc = {}
    if not gc:
        return say("FAIL", f"GatewayClass {c['className']}", "missing, or no Gateway API CRDs; cluster.gateway.install: true installs both")
    accepted = any(x["type"] == "Accepted" and x["status"] == "True" for x in gc.get("status", {}).get("conditions", []))
    say("PASS" if accepted else "WARN", f"GatewayClass {c['className']}", "" if accepted else "exists but is not Accepted by a controller")


def check_cert_manager(install):
    if install:
        return say("SKIP", "cert-manager", "the platform installs it")
    deploys = kget("deploy", "-A", "-l", "app.kubernetes.io/component=controller,app.kubernetes.io/name=cert-manager").get("items", [])
    if not deploys:
        return say("FAIL", "cert-manager", "no controller found; cluster.certManager.install: true installs it")
    text = json.dumps(deploys[0]["spec"]["template"])
    ns, name = deploys[0]["metadata"]["namespace"], deploys[0]["metadata"]["name"]
    enabled = "--enable-gateway-api" in text
    if not enabled:
        for cm in kget("cm", "-n", ns).get("items", []):
            enabled |= "enableGatewayAPI: true" in json.dumps(cm.get("data", {}))
    say("PASS" if enabled else "FAIL", f"cert-manager {ns}/{name}", "" if enabled else "enableGatewayAPI is off: HTTP-01 through the Gateway never solves")


def check_loadbalancer(c, timeout=60):
    if c["install"]:
        return say("SKIP", "LoadBalancer", "the platform installs MetalLB")
    svc = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "office-preflight", "namespace": "default"},
           "spec": {"type": "LoadBalancer", "ports": [{"port": 9, "targetPort": 9}]}}
    kubectl("apply", "-f", "-", input=json.dumps(svc))
    try:
        for _ in range(timeout // 2):
            ingress = kget("svc", "-n", "default", "office-preflight").get("status", {}).get("loadBalancer", {}).get("ingress")
            if ingress:
                return say("PASS", "LoadBalancer", f"a test Service got {ingress[0].get('ip') or ingress[0].get('hostname')}")
            time.sleep(2)
        say("FAIL", "LoadBalancer", f"no address in {timeout}s; nothing will hand the Gateway one (cluster.loadBalancer.install: true installs MetalLB)")
    finally:
        kubectl("delete", "svc", "-n", "default", "office-preflight", "--ignore-not-found")


def check_dns(path):
    out = subprocess.run([HERE / "dns.py", str(path), "--check"], capture_output=True, text=True)
    problems = [l.strip() for l in out.stdout.splitlines() if l.strip().startswith("!")]
    if out.returncode and not problems:
        return say("FAIL", "DNS", f"dns.py failed: {out.stderr.strip()[-200:]}")
    say("FAIL" if problems else "PASS", "DNS", "; ".join(problems))


def check_smtp(configured):
    host, port = os.environ.get("SMTP_HOST"), int(os.environ.get("SMTP_PORT", "587"))
    if host:
        try:
            socket.create_connection((host, port), timeout=5).close()
            return say("PASS", f"SMTP {host}:{port}", "reachable")
        except OSError as e:
            return say("FAIL", f"SMTP {host}:{port}", str(e))
    live = kget("secret", "-n", "office-data", "--ignore-not-found", "smtp-credentials")
    if live and live["metadata"].get("labels", {}).get("office.haaijer.dev/placeholder") != "true":
        return say("PASS", "SMTP", "smtp-credentials exists")
    if configured:
        return say("WARN", "SMTP", "smtp.configured is true and no smtp-credentials Secret: every backend pod waits for it")
    say("WARN", "SMTP", "not configured — invitations and password reset will not work")


MONITORING_NS, OURS = "office-monitoring", {"office.haaijer.dev/monitoring": "true"}
NS_LABELS = {"kubernetes.io/metadata.name": MONITORING_NS}


def selects(selector, labels):
    """A Kubernetes label selector against a label set; a missing selector selects nothing."""
    if selector is None:
        return False
    ok = all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items())
    for e in selector.get("matchExpressions", []):
        has, val = e["key"] in labels, labels.get(e["key"])
        ok &= {"In": has and val in e.get("values", []), "NotIn": not has or val not in e.get("values", []),
               "Exists": has, "DoesNotExist": not has}[e["operator"]]
    return ok


def check_monitoring(m, smtp_configured):
    """adr/0119: platform needs the CRDs to be its own, external needs someone else's."""
    mode = m.get("mode", "platform")
    if mode == "none":
        return say("WARN", "monitoring", "mode: none — nothing alerts when the platform stops serving")
    crds = [c for c in kget("crd").get("items", []) if c["metadata"]["name"].endswith(".monitoring.coreos.com")]
    if mode == "platform":
        foreign = [c["metadata"]["name"] for c in crds
                   if c["metadata"].get("labels", {}).get("helm.toolkit.fluxcd.io/namespace") != MONITORING_NS]
        if foreign:
            return say("FAIL", "monitoring", f"another Prometheus operator's CRDs exist ({foreign[0]}…): two operators "
                       "fight over them; choose monitoring.mode: external, or remove it first")
        say("PASS", "monitoring", "no other Prometheus operator")
        if not m.get("email"):
            say("WARN", "monitoring", "no monitoring.email: alerts are evaluated and sent nowhere")
        elif not smtp_configured:
            say("WARN", "monitoring", "smtp.configured is false: alerts cannot be delivered")
        return
    if not crds:
        return say("FAIL", "monitoring", "mode: external, but no Prometheus operator CRDs on this cluster")
    for p in kget("prometheus", "-A").get("items", []):
        spec, own_ns = p["spec"], {"kubernetes.io/metadata.name": p["metadata"]["namespace"]}
        missing = [kind for kind in ("rule", "probe", "serviceMonitor")
                   if not selects(spec.get(f"{kind}Selector"), OURS)
                   or not (selects(spec.get(f"{kind}NamespaceSelector"), NS_LABELS)
                           if f"{kind}NamespaceSelector" in spec else own_ns == NS_LABELS)]
        if not missing:
            say("PASS", f"Prometheus {p['metadata']['namespace']}/{p['metadata']['name']}",
                "selects the platform's rules, probes and scrapes")
            break
    else:
        say("WARN", "monitoring", "no Prometheus selects PrometheusRules, Probes and ServiceMonitors labelled "
            f"office.haaijer.dev/monitoring=true in {MONITORING_NS}: the platform's rules will never run")
    say("WARN", "monitoring", "external: the Longhorn rules need its metrics scraped, and Flux's alerts are yours "
        "to wire (docs/install.md, Monitoring)")


def check_shutdown(storage_class):
    """The 2026-10-18 outage: a reboot without graceful shutdown tore Longhorn's volumes
    out from under Valkey. configz shows the kubelet's settings, not logind's cap on them."""
    if storage_class != "longhorn":
        return
    for node in kget("nodes").get("items", []):
        name = node["metadata"]["name"]
        raw = kubectl("get", "--raw", f"/api/v1/nodes/{name}/proxy/configz")
        cfg = json.loads(raw).get("kubeletconfig", {}) if raw else {}
        if cfg.get("shutdownGracePeriod", "0s") in ("0s", "") and not cfg.get("shutdownGracePeriodByPodPriority"):
            say("WARN", f"node {name}", "kubelet has no graceful shutdown: a reboot cuts Longhorn volumes "
                "mid-write (adr/0119). A logind InhibitDelayMaxSec cap can still defeat it; this cannot see that")
        else:
            say("PASS", f"node {name}", "kubelet shuts down gracefully (logind's cap not checked)")


def check_hf(meet):
    token = os.environ.get("HF_TOKEN")
    if not meet:
        return say("SKIP", "Hugging Face", "Meet is off")
    if not token:
        return say("WARN", "Hugging Face", "no HF_TOKEN: transcripts will not work")
    req = urllib.request.Request("https://huggingface.co/pyannote/segmentation-3.0/resolve/main/config.yaml",
                                 headers={"Authorization": f"Bearer {token}"}, method="HEAD")
    try:
        urllib.request.urlopen(req, timeout=10)
        say("PASS", "Hugging Face", "token reads the gated model")
    except urllib.error.HTTPError as e:
        say("FAIL", "Hugging Face", f"{e.code}: accept the terms on pyannote/segmentation-3.0 and speaker-diarization-3.1")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cluster", type=pathlib.Path, help="the file install.sh writes, or a bare values file")
    path = ap.parse_args().cluster
    v = render.org_values(path)
    defaults = render.load((HERE / "charts/control-plane/values.yaml").read_text())
    cluster = {k: defaults["cluster"][k] | v.get("cluster", {}).get(k, {}) for k in defaults["cluster"]}
    kubectl("cluster-info", check=True)
    check_flux_operator()
    check_storage(v.get("storageClass", defaults["storageClass"]))
    check_gateway(cluster["gateway"])
    check_cert_manager(cluster["certManager"]["install"])
    check_loadbalancer(cluster["loadBalancer"])
    check_dns(path)
    smtp = v.get("smtp", defaults["smtp"])["configured"]
    check_smtp(smtp)
    check_monitoring(defaults["monitoring"] | v.get("monitoring", {}), smtp)
    check_shutdown(v.get("storageClass", defaults["storageClass"]))
    table = render.load((HERE / "charts/control-plane/apps.yaml").read_text())
    check_hf(v.get("apps", {}).get("meet", table["meet"]["default"]))
    print("\nFAIL — fix the above before applying" if failed else "\nready")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
