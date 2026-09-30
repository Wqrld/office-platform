#!/usr/bin/env python3
"""Is this cluster ready for this cluster.yaml? Run before `kubectl apply -f cluster.yaml`.

    ./preflight.py cluster.yaml        the file install.sh writes, or a bare values file

Checks what the platform assumes and cannot install itself, and skips what
`cluster.*.install` says it will. Exit 1 on any FAIL. SMTP_HOST/SMTP_PORT and HF_TOKEN
are read from the environment, as install.sh sets them.
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
failed = False


def say(status, what, detail=""):
    global failed
    failed |= status == "FAIL"
    print(f"{status:4} {what}" + (f" — {detail}" if detail else ""))


def kubectl(*args, check=False):
    out = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if check and out.returncode:
        raise RuntimeError(out.stderr.strip())
    return out.stdout


def kget(*args):
    out = kubectl("get", *args, "-o", "json")
    return json.loads(out) if out else {}


def values_of(path):
    docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    hr = next((d for d in docs if d.get("kind") == "HelmRelease"), None)
    return hr["spec"]["values"] if hr else docs[0]


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
    subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(svc), text=True, capture_output=True)
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


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = pathlib.Path(sys.argv[1])
    v = values_of(path)
    defaults = yaml.safe_load((HERE / "charts/control-plane/values.yaml").read_text())
    cluster = {k: defaults["cluster"][k] | v.get("cluster", {}).get(k, {}) for k in defaults["cluster"]}
    kubectl("cluster-info", check=True)
    check_flux_operator()
    check_storage(v.get("storageClass", defaults["storageClass"]))
    check_gateway(cluster["gateway"])
    check_cert_manager(cluster["certManager"]["install"])
    check_loadbalancer(cluster["loadBalancer"])
    check_dns(path)
    check_smtp(v.get("smtp", defaults["smtp"])["configured"])
    table = yaml.safe_load((HERE / "charts/control-plane/apps.yaml").read_text())
    check_hf(v.get("apps", {}).get("meet", table["meet"]["default"]))
    print("\nFAIL — fix the above before applying" if failed else "\nready")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
