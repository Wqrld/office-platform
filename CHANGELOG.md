# Changelog

One version covers the config and all four charts (`docs/releasing.md`). A cluster
upgrades by changing `ref.tag` in its `cluster.yaml`.

## Unreleased

- **Breaking: a release is a git tag; there is no registry** (`docs/adr/0114`). The control
  plane reads the config and the platform charts from this repository at `v<version>`.
  `registry: {url, pullSecret}` is replaced by `source: {url, secretRef}`, which defaults
  to the public repository; in `cluster.yaml` the `platform` OCIRepository becomes a
  GitRepository and the HelmRelease takes `chart.spec` from it (`examples/cluster.yaml`).
  `install.sh` takes `SOURCE_URL`/`SOURCE_SECRET` instead of `REGISTRY`/`HARBOR_*`.

- Test cases and goldens use `example.org` and documentation addresses; `cluster-prod` and
  `cluster-demo` are now `cluster-default` and `cluster-small`.

## 2.2.14 — 2026-10-04
- `gateway.extraCertificates`: serve hosts routed outside the platform on the shared Gateway.

## 2.2.13 — 2026-10-04
- Apps watch their sizes ConfigMaps, so a release lands whole.

## 2.2.12 — 2026-10-04
- Celery workers: no readiness probe, liveness every 5 minutes.

## 2.2.6 – 2.2.11 — 2026-10-03
- Drive: document thumbnails and a grid view in the explorer (fork `v0.23.0-office.1`–`.6`).
- Each app's Celery keys are prefixed on the shared broker.

## 2.2.5 — 2026-10-02
- Calendars is charted from the fork's git tag, like Projects and Messages.

## 2.2.0 – 2.2.4 — 2026-09-30
- New app: Messages (off by default), with an inbound MTA through the Gateway.
- Fixes: Valkey ACLs for Messages, backend user and liveness path, the MX certificate.

## 2.1.0 – 2.1.1 — 2026-09-27
- New app: Projects. `install.sh` for a fresh VPS (`--k3s`) or an existing cluster.
- Gateway controller, cert-manager and MetalLB are optional layers the platform can install
  (`docs/adr/0112`).

## 2.0.0 – 2.0.1 — 2026-09-16
- One repository and one organisation file: the `control-plane` chart renders a whole
  cluster from `examples/cluster.yaml`. Meet and LiveKit added.
- Pins come from `appVersion`; every object is kept on uninstall; Helm does not wait.
