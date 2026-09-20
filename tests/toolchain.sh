#!/usr/bin/env bash
# Install the named tools at the versions the environment pins (`HELM_VERSION`, ...):
#   ./tests/toolchain.sh helm flux kubeconform conftest dyff gitleaks
# Pinned binaries fetched with curl, not marketplace actions — the same decision as pinning
# actions to commit SHAs, applied to the toolchain. CI's one place for every install.
set -euo pipefail

need() { local v="${1^^}_VERSION"; [[ -n "${!v:-}" ]] || { echo "toolchain: $v is not set" >&2; exit 2; }; echo "${!v}"; }
get()  { curl -fsSL "$1" | tar xz -C /tmp "${@:2}"; }
put()  { sudo install -m755 "/tmp/$1" "/usr/local/bin/$(basename "$1")"; }

for tool in "$@"; do
  v="$(need "$tool")"
  case "$tool" in
    helm)        get "https://get.helm.sh/helm-v${v}-linux-amd64.tar.gz" linux-amd64/helm; put linux-amd64/helm ;;
    flux)        get "https://github.com/fluxcd/flux2/releases/download/v${v}/flux_${v}_linux_amd64.tar.gz" flux; put flux ;;
    kubeconform) get "https://github.com/yannh/kubeconform/releases/download/v${v}/kubeconform-linux-amd64.tar.gz" kubeconform; put kubeconform ;;
    conftest)    get "https://github.com/open-policy-agent/conftest/releases/download/v${v}/conftest_${v}_Linux_x86_64.tar.gz" conftest; put conftest ;;
    dyff)        get "https://github.com/homeport/dyff/releases/download/v${v}/dyff_${v}_linux_amd64.tar.gz" dyff; put dyff ;;
    gitleaks)    get "https://github.com/gitleaks/gitleaks/releases/download/v${v}/gitleaks_${v}_linux_x64.tar.gz" gitleaks; put gitleaks ;;
    *) echo "toolchain: unknown tool $tool" >&2; exit 2 ;;
  esac
  echo "installed $tool $v"
done
