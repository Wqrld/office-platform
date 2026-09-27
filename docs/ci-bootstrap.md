# Nightly bootstrap from scratch — design

`install.md` has never been run end to end by a machine (`e2e.py` reads `DOMAIN`, `E2E_USER`, `E2E_PASSWORD`). This makes it run every night,
so the day it stops working is the day it broke.

**Shape.** One VPS that is nothing but this: a GitLab runner with the shell executor,
`ci.<domain>` and `*.ci.<domain>` pointing at it, Let's Encrypt staging so a red night
costs no rate limit. The job tears the cluster down, installs from nothing, waits for every
Kustomization, logs in and uploads a file, and keeps the logs.

```yaml
# .gitlab-ci.yml
bootstrap:
  stage: nightly
  tags: [office-bootstrap]                # the one runner on that VPS
  rules: [{if: $CI_PIPELINE_SOURCE == "schedule"}]
  timeout: 90m
  variables:
    DOMAIN: ci.example.org
    ACME_EMAIL: ops@example.org
    TLS_ISSUER: letsencrypt-gateway-staging
  script:
    - mkdir -p logs
    - sudo /usr/local/bin/k3s-uninstall.sh || true
    - ./install.sh --k3s --no-watch
    - flux get kustomizations -A --watch --timeout 60m
    - kubectl -n office-system wait certificate/office-tls --for=condition=Ready --timeout=15m
    - apps/drive/e2e.py | tee logs/e2e.txt
  after_script:
    - flux get all -A > logs/flux.txt; kubectl get pods -A > logs/pods.txt
    - kubectl get events -A --sort-by=.lastTimestamp > logs/events.txt
  artifacts:
    when: always
    paths: [logs/]
```

`SMTP_*`, `HF_TOKEN`, `E2E_*` and `HARBOR_*` are masked CI variables; `install.sh` reads
them from the environment. The realm ships no users, so the job creates one through the
Keycloak admin API before `e2e.py` — a dozen lines with the bootstrap-admin Secret, or
`platform/identity/add-user.sh` if that grows.

**Why a VPS and not k3d in a job.** The point is the real path: a public address, DNS,
HTTP-01 through the Gateway, MetalLB on a real interface, a real certificate chain. k3d in a
runner container proves the manifests apply — `tests/build.py` already proves most of that
— and would need a fake issuer, no LoadBalancer, and its own network shape, which is a
second install path to keep working. The VPS costs a machine; k3d costs a parallel truth.

**What the runner needs**: sudo without a password for `k3s-uninstall.sh` and `install.sh`,
`helm flux kubectl yq python3` from `tests/toolchain.sh`, and nothing else on it that
matters, because the job wipes the cluster every night. Add `--upgrade-from <version>` to
the same job later and it is the upgrade test too.
