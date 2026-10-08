# Changelog

One version covers the config and all four charts (`docs/releasing.md`). A cluster
upgrades by changing `ref.tag` in its `cluster.yaml`.

## Unreleased

- Fix: Docs' full-text search returned 401 once the user had gone 30 minutes without a
  search, until they logged in again. The Keycloak session (SSO idle timeout and max
  lifespan) now lasts 12 hours, as long as the Docs session (`docs/adr/0116`).

## 2.3.2 — 2026-10-07

- Fix: upgrading `platform-tenants` failed on the `realm-<hash>` Job whenever only the chart
  version changed, since a Job's template is immutable (2.3.1 stalled on it). The realm and
  OpenSearch Job names now hash their whole input and the chart version, so each release
  runs them afresh.

## 2.3.1 — 2026-10-07

- Upstream bumps: Meet v1.34.0, Docs v5.7.0, Keycloak operator 26.8.0, garage-operator
  0.8.2, external-secrets 2.12.0, cloudnative-pg 0.29.1, Collabora 1.3.5, livekit-server
  v1.13.9, egress v1.15.0.
- updatecli writes valid pins: multi-line targets no longer insert a literal `\n`, and
  Find's pin tracks main's HEAD commit instead of a branch name.

## 2.3.0 — 2026-10-07

- **Breaking: a release is a git tag; there is no registry** (`docs/adr/0114`). The control
  plane reads the config and the platform charts from this repository at `v<version>`.
  `registry: {url, pullSecret}` is replaced by `source: {url, secretRef}`, which defaults
  to the public repository; in `cluster.yaml` the `platform` OCIRepository becomes a
  GitRepository and the HelmRelease takes `chart.spec` from it (`examples/cluster.yaml`).
  `install.sh` takes `SOURCE_URL`/`SOURCE_SECRET` instead of `REGISTRY`/`HARBOR_*`.

- Test cases and goldens use `example.org` and documentation addresses; `cluster-prod` and
  `cluster-demo` are now `cluster-default` and `cluster-small`.
- **Tenants phase 2:** `platform-tenants` alone provisions each app's database, role, cache
  users, OIDC client Secret and bucket grant; the 197 hand-written objects leave the
  Kustomizations, all `prune: disabled`. keycloak-config-cli owns the realm through a
  `realm-<hash>` Job (`platform/identity/README.md`, first rollout on a live realm), and an
  `opensearch-security-<hash>` Job owns OpenSearch's users and roles.
- `charts/control-plane/apps.yaml` is the one per-app registry: what each app is provisioned
  and whether it is on by default.
- Surrounds: `routes[].host` defaults to the app, `staticFiles.enabled` implies the `/custom`
  route; one shared no-PDB size file for `small` and `medium`.
- Identity: email is admin-only in the realm's user profile.

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
