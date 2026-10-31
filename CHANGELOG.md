# Changelog

One version covers the config and all four charts (`docs/releasing.md`). A cluster
upgrades by changing `ref.tag` in its `cluster.yaml`.

## Unreleased

## 2.5.2 — 2026-10-31

- Docs from the fork `Wqrld/docs` at `v6.0.4-office.1`: upstream `main` after 6.0.4 (the
  6.0.4 security fixes, a dedicated abilities endpoint yhub now reads, BlockNote 0.56 with
  Typst PDF export, user mentions) plus the document title in exports, with an option to
  leave it out. Chart and the four images move with one tag (`apps/docs/README.md`, The
  fork). No migration. The old `flux-system/suitenumerique-docs` GitRepository stays behind;
  delete it by hand after the upgrade.
- Find, Meet, Drive and Messages start gunicorn with `--no-control-socket`. Gunicorn 25's
  runtime control socket defaulted to `/.gunicorn` on a read-only root, and every start
  logged `Control server error`. Nothing used it: Kubernetes manages the workers.

## 2.5.1 — 2026-10-25

- Upstream bumps: Docs 6.0.3, Meet 1.36.3, Find `main@bb2aa09`, LiveKit server 1.13.11,
  Collabora chart 1.3.7 with CODE 26.04.5.2.1, external-secrets 2.14.0,
  kube-prometheus-stack 92.13.1, blackbox exporter 11.20.2. Mostly security fixes. Docs'
  yhub schema job runs again on the upgrade (6.0.2 adds a table). Meet 1.36 would let any
  signed-in participant start a transcript; it stays limited to room admins and owners.

## 2.5.0 — 2026-10-19

- ⚠️ Monitoring, on by default (`docs/adr/0119`). Upgrading installs Prometheus,
  Alertmanager, kube-state-metrics and a blackbox exporter in `office-monitoring` unless
  `cluster.yaml` sets `monitoring.mode: none`. They alert, by email to `monitoring.email`,
  on a crash-looping pod, a workload with no available replica, a Service with no ready
  endpoint, a public host that does not answer below 500, a node condition, a degraded
  Longhorn volume, a full volume, and a certificate within 14 days of expiry. Measured on a
  ~50-pod cluster: about 1,100 series, 120 Mi and 0.02 cores in use; 176 Mi and 30m
  requested, plus 6 Gi of volumes. A cluster that already runs a Prometheus operator must
  choose `mode: external` (the rules and probes only) or remove its operator first:
  `preflight.py` refuses otherwise. `preflight.py` also warns when a Longhorn node's
  kubelet has no graceful shutdown.
- The Valkey instances and OpenSearch correct drift: a hand-scaled or hand-edited
  datastore is put back, and Flux reports it.

## 2.4.0 — 2026-10-12

- ⚠️ Docs 6.0.0: the collaboration server is yhub (`docs/adr/0118`). The editor's websocket
  and document routes go to it; the `y-provider` only converts. Before this release reaches a
  cluster, do the steps in `apps/docs/README.md` (Upgrade to 6.0.0): the `yhub` database and
  its keys come with it. Documents must be migrated before `SOFT_MIGRATION` is turned off, or
  they open empty. Valkey's `docs` user gets `+info +keys` on the `cache` instance for yhub.
- Checks: `startup.py` knows that a Role letting a release create a Secret produces the
  Secret it names, as the chart's JWT job does.
- Maintenance: nothing a cluster applies changes. `measure.py` now counts Drive's and
  Meet's CronJobs, which it missed before, so its totals rise (small: 2270m / 16544Mi for
  the apps). Every script takes `--help`; `release.sh` runs on macOS; the label domain
  stays as it is (`docs/adr/0117`).

## 2.3.4 — 2026-10-08

- Security: read-only root filesystems for Docs, Drive, Meet, Find, Calendars (not
  caldav), the LiveKit server and Messages' backend, as mijn-bureau runs the same images.
  Each gets an emptyDir at /tmp; Calendars' Caddy also at its two XDG directories.
  Calendars' backend and frontend state `runAsUser: 1001`, so an upstream image runs
  non-root too.
- Security: read-only root filesystems for the rest of the apps too: Messages' frontend,
  MTA and MPA, Projects, Calendars' caldav, Meet's whisperx, LiveKit egress, the Keycloak
  operator and Garage. Still writable: Collabora, Keycloak, OpenSearch.

## 2.3.3 — 2026-10-08

- Security: every response carries HSTS (1 year) and `X-Content-Type-Options: nosniff`;
  realm passwords need 12 characters, not the username or email, and not one of the last
  3 (checked at the next change); app pods no longer mount a Kubernetes API token.
- Security: every app pod except Collabora now meets Pod Security `restricted`. Meet and
  Find drop all capabilities and run non-root; Calendars' caldav runs as `www-data`
  instead of root; OpenSearch has no root `chown` initContainer.
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
