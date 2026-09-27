#!/usr/bin/env bash
# From nothing to a reconciling platform. docs/install.md explains each step.
#
#   DOMAIN=office.example.org ACME_EMAIL=ops@example.org ./install.sh --k3s
#   DOMAIN=... ACME_EMAIL=... GATEWAY_IP=10.0.0.5 ./install.sh --existing
#
# Optional: SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD
# SMTP_FROM SMTP_TLS=starttls|ssl, HF_TOKEN, HARBOR_USER HARBOR_PASSWORD, VERSION, REGISTRY,
# SIZE=small|medium|large, STORAGE_CLASS, TLS_ISSUER, GATEWAY_CLASS, OUT=cluster.yaml.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUX_OPERATOR=v0.59.0
K3S_VERSION="${K3S_VERSION:-v1.34.2+k3s1}"
MODE=""; WATCH=1
for arg in "$@"; do
  case "$arg" in
    --k3s|--existing) MODE="${arg#--}" ;;
    --no-watch) WATCH=0 ;;
    *) echo "usage: $0 --k3s|--existing [--no-watch]" >&2; exit 2 ;;
  esac
done
[[ -n "$MODE" ]] || { echo "usage: $0 --k3s|--existing [--no-watch]" >&2; exit 2; }
: "${DOMAIN:?}" "${ACME_EMAIL:?}"
OUT="${OUT:-$HERE/cluster.yaml}"
REGISTRY="${REGISTRY:-oci://harbor.mijnbureau.haaijer.dev/office}"
VERSION="${VERSION:-$(sed -n 's/^appVersion: "\(.*\)"/\1/p' "$HERE/charts/control-plane/Chart.yaml")}"

echo "== 1. cluster ($MODE)"
if [[ "$MODE" == k3s ]]; then
  if ! command -v k3s >/dev/null; then
    curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - server \
      --disable traefik --disable servicelb --write-kubeconfig-mode 644
  fi
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
  GATEWAY_IP="${GATEWAY_IP:-$(curl -sf https://api.ipify.org || hostname -I | awk '{print $1}')}"
  STORAGE_CLASS="${STORAGE_CLASS:-local-path}"
  INSTALL=true; LB_KIND=metallb
else
  : "${GATEWAY_IP:?set GATEWAY_IP to the address your LoadBalancer gives the Gateway}"
  STORAGE_CLASS="${STORAGE_CLASS:-$(kubectl get sc -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}')}"
  INSTALL="${INSTALL:-false}"; LB_KIND="${LB_KIND:-none}"
fi
kubectl cluster-info >/dev/null

echo "== 2. $OUT"
export DOMAIN ACME_EMAIL GATEWAY_IP STORAGE_CLASS INSTALL LB_KIND REGISTRY VERSION OUT
python3 - "$HERE/examples/cluster.yaml" <<'PY'
import os, sys, yaml
e = os.environ.get
flux, oci, hr = yaml.safe_load_all(open(sys.argv[1]))
oci["spec"]["url"] = f"{e('REGISTRY')}/charts/control-plane"
oci["spec"]["ref"] = {"tag": e("VERSION")}
v = hr["spec"]["values"]
v.update(domain=e("DOMAIN"), storageClass=e("STORAGE_CLASS"), size=e("SIZE", "small"))
v["gateway"] = {"ip": e("GATEWAY_IP"), "acmeEmail": e("ACME_EMAIL"), "tlsIssuer": e("TLS_ISSUER", "letsencrypt-gateway")}
install = e("INSTALL") == "true"
pool = [f"{e('GATEWAY_IP')}/32"]
v["cluster"] = {"gateway": {"install": install, "className": e("GATEWAY_CLASS", "eg")},
                "certManager": {"install": install},
                "loadBalancer": {"kind": e("LB_KIND"), "install": install, "pool": pool}}
v["smtp"] = {"configured": bool(e("SMTP_HOST"))}
v["registry"] = {"url": e("REGISTRY")}
if e("HARBOR_USER"):
    v["registry"]["pullSecret"] = "harbor-auth"
else:
    oci["spec"].pop("secretRef", None)
yaml.safe_dump_all([flux, oci, hr], open(e("OUT"), "w"), sort_keys=False)
PY
python3 -c 'import sys,yaml; print(yaml.safe_dump(list(yaml.safe_load_all(open(sys.argv[1])))[2]["spec"]["values"]))' "$OUT" > "$OUT.values"
helm template platform "$HERE/charts/control-plane" --values "$OUT.values" >/dev/null
rm "$OUT.values"
"$HERE/preflight.py" "$OUT"

echo "== 3. secrets"
for ns in flux-system office-data; do
  kubectl get ns "$ns" >/dev/null 2>&1 || kubectl create ns "$ns"
done
if [[ -n "${HARBOR_USER:-}" ]]; then
  kubectl -n flux-system create secret docker-registry harbor-auth --docker-server="${REGISTRY#oci://}" \
    --docker-username="$HARBOR_USER" --docker-password="$HARBOR_PASSWORD" --dry-run=client -o yaml | kubectl apply -f -
fi
if [[ -n "${SMTP_HOST:-}" ]]; then
  tls=$([[ "${SMTP_TLS:-starttls}" == starttls ]] && echo true || echo false)
  ssl=$([[ "${SMTP_TLS:-starttls}" == ssl ]] && echo true || echo false)
  kubectl -n office-data create secret generic smtp-credentials \
    --from-literal=host="$SMTP_HOST" --from-literal=port="${SMTP_PORT:-587}" \
    --from-literal=username="$SMTP_USERNAME" --from-literal=password="$SMTP_PASSWORD" \
    --from-literal=useTLS="$tls" --from-literal=useSSL="$ssl" \
    --from-literal=from="${SMTP_FROM:-noreply@$DOMAIN}" --dry-run=client -o yaml | kubectl apply -f -
else
  echo "   SMTP not configured — invitations and password reset will not work (docs/install.md, Mail)"
fi
if [[ -n "${HF_TOKEN:-}" ]]; then
  kubectl -n office-data create secret generic huggingface --from-literal=token="$HF_TOKEN" --dry-run=client -o yaml | kubectl apply -f -
fi

echo "== 4. flux"
kubectl apply -f "https://github.com/controlplaneio-fluxcd/flux-operator/releases/download/$FLUX_OPERATOR/install.yaml" >/dev/null
kubectl -n flux-system rollout status deploy/flux-operator --timeout=5m >/dev/null
kubectl apply -f "$OUT"
echo "   applied. keep $OUT — re-applying it is the upgrade (docs/install.md §2)."
(( WATCH )) && exec flux get kustomizations --watch
exit 0
