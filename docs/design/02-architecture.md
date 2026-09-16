# 02 — Architecture

## Principles

Five rules. Nearly every decision downstream follows from them.

**P1 — Publish the base; don't copy it.**
The shared chart is a versioned OCI artifact, not files vendored into the config repo.
Consumers reference a version. Upgrades are a version bump, not a merge conflict.

**P2 — Never re-model a Kubernetes API.**
Probes, volumes, resources, tolerations, affinity, securityContext, topology spread are
accepted verbatim and spliced through with `toYaml`. No `probes.liveness.httpGet.path` as a
bespoke value. You inherit the real schema, the real docs, and zero maintenance. This one
rule removes most per-app variation.

**P3 — Model only what Kubernetes lacks.**
`host`, `oidc.client`, `database.secretName`, `egress`. The chart's real API should fit on
one screen.

**P4 — Contracts, not implementations.**
The app chart knows "a Secret exists at this name with these keys." It does not know what
CloudNativePG is. This is what makes bring-your-own-database a config change.

**P5 — Exceptions have a home.**
Used once, it goes in the escape hatch. Used three times, it becomes a chart feature.
Without this rule every odd app permanently widens the shared API.

**P6 — Don't build for requirements we don't have.**
Added to the original five, because the biggest risk to this project is not under-designing.
Every operator we install is an upgrade cycle we own forever. See "Deferred" below.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Delivery | **Flux v2** | `OCIRepository` + semver range *is* "track upstream". `dependsOn` with health gating is the ordering primitive we currently fake with string-concatenated `needs:`. |
| Packaging | **Upstream Helm charts + our surround chart**, OCI-published | DINUM maintains charts for most apps; we build what wraps them. `adr/0012` |
| Invariants | **Kyverno** mutate + validate | Reaches every pod, not only ones we template. `adr/0013` |
| Ingress | **Envoy Gateway**, Gateway API v1.x | The old repo already migrated most apps to HTTPRoute; finishing the job removes 24 Ingress templates. See caveats below. |
| Identity | **Keycloak Operator** + realm config in git | Operator runs the instance. Realm/clients stay declarative config — see `07-identity-and-secrets.md`. |
| Postgres | **CloudNativePG**, one shared Cluster | Already in use here and working. A `Database` + `Role` per app, one PgBouncer `Pooler`, Barman → object storage for backups. |
| Cache | **Valkey**, via a small operator-free chart | Replaces Bitnami Redis. Two shared instances — cache and broker — see `06`. |
| Object storage | **Garage** via `garage-operator` | 3 apps need S3. External S3 is a first-class mode. `adr/0009` |
| Search | **OpenSearch** (official chart) | One shared instance. Already proven here for `find`. |
| Secrets | **External Secrets Operator** + SOPS/age for bootstrap roots | Replaces render-time `derivePassword`. See `07`. |
| Observability | kube-prometheus-stack + grafana-operator | ServiceMonitor and PrometheusRule generated from app values. |
| Policy | Kyverno, audit mode first + Pod Security Admission `restricted` | Backstop for the invariants below, not a place to hide config. PSA is the free, boring baseline; Kyverno covers what PSA cannot express. |

## Corrections to the original proposal

The colleague's proposal is sound and most of it carries over. Six things need adjusting
before anyone builds on it, all learned from what these applications actually are.

### 1. The 80/20 split is real — but upstream already owns the 80

The proposal's centrepiece was a `platform-app` chart handling most apps in ~25 lines. Our
first draft rejected that as too optimistic, because nine of fifteen apps are multi-workload
and Docs has five.

Both were reasoning about the wrong thing. **DINUM publishes and actively maintains charts
for Docs, Drive, Meet, Conversations, Find and People** (`adr/0012`), and vendor or community
charts exist for Keycloak, LiveKit, OpenSearch, Collabora, Ollama, Grist and Element (via
Element's own AGPL-3.0 ESS chart). Only Calendars and Bureaublad have none.

So the proposal's instinct was right and its target was wrong. `platform-app` is real and
apps really are ~25–70 lines — but it is a **surround** chart (routes, network policy,
disruption budget, observability) wrapping a workload someone else's chart created, not a
chart that generates the workload. See `04-platform-charts.md`.

### 2. Edge OIDC is mostly a non-benefit here

The proposal justifies Envoy Gateway partly on `SecurityPolicy` doing OIDC at the edge,
"no oauth2-proxy sidecar ×10". But Docs, Drive, Meet, Conversations, Calendars, Find,
Bureaublad and Grist all do OIDC **in-app** — mozilla-django-oidc for the Django apps, with
their own sessions and user provisioning (see `apps/docs/values.yaml.gotmpl:202-232`,
22 `OIDC_*` variables). Fronting them with edge OIDC double-authenticates.

Edge OIDC is useful for the handful without it. Envoy Gateway may still be right — for
`SecurityPolicy`, rate limiting, and a maintained Gateway API implementation — but choose it
on those grounds, and don't design the app contract around edge auth.

### 3. Bootstrap and migration Jobs are a first-class concern

Absent from the proposal, and needed by at least six apps: Django `migrate`, waffle flag
creation, Keycloak realm application, OpenSearch index creation.

Mostly resolved by `adr/0012` — upstream charts ship their own migration Jobs. What remains
is handling *their* Job bugs. Find's chart names its migrate Job
`find-backend-migrate-{chartVersion}` and the version rarely moves, so the immutable
`spec.template` breaks every upgrade. Set `install.disableWaitForJobs` and
`upgrade.disableWaitForJobs` on every release, never auto-rollback a release that migrates a
schema, and treat upstream Job defects as `known-limitations.md` entries with `postRenderers`
patches.

Our own two charts use `platform.jobs`: Helm hooks with
`hook-delete-policy: before-hook-creation`, never timestamp-suffixed names — which is what
the old repo resorted to because Helm hooks and ArgoCD don't compose.

### 4. Cut RabbitMQ. Probably cut Crossplane.

**RabbitMQ: nothing in this suite uses AMQP.** Celery here runs on Redis as its broker.
The proposal's `platform-datastore` with RabbitMQ Cluster Operator + Messaging Topology
Operator + external-broker mode is two operators and a schema branch for a requirement that
does not exist. That is P5 violated in the proposal itself.

**Crossplane** is introduced for `provider-keycloak` and `provider-sql`. That is a control
plane plus provider lifecycle for ten OIDC clients and external-DB provisioning we may never
use. The old repo already does working realm configuration declaratively via
keycloak-config-cli — 820 lines, 11 clients (ten after the cut and the People addition),
correct mappers and scopes. Start with
realm-as-config; add Crossplane if and when drift actually bites.

Neither is a permanent no. Both are "not in v1". See `adr/0007`.

### 5. Ten apps do not justify a service mesh — and now nor does a big library chart

The proposal rejected a service mesh on the grounds that ten apps do not justify a control
plane and its upgrade cycle. The same reasoning, applied honestly, cuts against a large
library chart once upstream charts exist: fourteen hand-maintained charts is a maintenance
burden we would own forever, to duplicate work done upstream continuously.

### 6. The Bitnami removal list is incomplete

The proposal names the images and the charts we replace. It omits the item that is actually
the work: **the `common` library chart**, which 23 authored charts depend on and whose idiom
they are written in. It also omits:

- **MinIO** — Bitnami MinIO backs Docs, Drive and Grist. Replaced by Garage (`adr/0009`).
- **Bitnami nginx** — used as a per-app static-asset server. Should be deleted, not replaced
  (see below).
- **Bitnami Keycloak chart** — replaced by the Keycloak Operator.

### 7. Two items the proposal doesn't cover — now settled

**Object storage.** Three apps need S3. Settled: **Garage via `garage-operator`** for the
managed path, with external S3 as a first-class mode on the same contract. `adr/0009` records
the operator's maturity risk honestly and why P4 makes it acceptable.

**LiveKit does not fit Gateway API.** WebRTC media is UDP and ICE, which an L7 proxy cannot
carry. Built as a dedicated `Service type=LoadBalancer` on its own MetalLB address
(`LIVEKIT_IP`) for media and TURN/UDP, with signaling still on the shared Gateway — the one
documented exception (`config/apps/livekit/README.md`). No TURN/TLS, per adr/0105.

## Design decisions specific to us

### Kill the static-nginx-per-app pattern

Five apps ship an entire nginx release to serve theme assets. Upstream charts do not have
this pattern at all, so `adr/0012` deletes it for free: 5 releases, ~5,000 lines, 5 hostnames.

### Size profiles carry the 5-to-5,000 range

One set of app files; `small` / `medium` / `large` as one Kustomize patch each, applying to
every app (`05-app-contract.md`). We are configuring the upstream charts' own replica and
autoscaling knobs — which DINUM runs at scale — rather than inventing our own.

### Don't vendor Grafana dashboards

47,885 lines of dashboard JSON are vendored today. `grafanaoperator`'s `GrafanaDashboard`
supports `grafanaCom: {id: …}` and `url:`. Keep only genuinely custom dashboards in git.

### Reconsider per-app cache

Ten Redis instances back Django caches and Celery brokers. At this scale shared Valkey with
per-app logical databases and per-app credentials is far less to run, patch and back up.
The proposal inherits "per-app cache" without examining it. Recommendation: **two shared
Valkey instances** — an evicting cache and a non-evicting broker, because eviction policy is
per-instance and an evicting broker silently drops Celery tasks — each with a per-app ACL
user and logical DB. Keep the *contract* per-app (`06-datastores.md`) so splitting further
later is a config change.

### Add a "shared service" category

`find`/OpenSearch is one instance serving indices for several apps. The proposal models
everything as per-app datastores and has no notion of a cross-app backing service.
`platform-deps` (the proposal called it `platform-datastore`; it grew to own OIDC secrets
and service tokens too, so it is named for the role rather than the kind) needs a
`scope: shared | app` dimension.

## Operational invariants

Encoded in the library chart, backstopped by Kyverno.

- **PDBs only when replicas > 1, always `maxUnavailable`** — decided by the size profile,
  which sets replicas and `pdb.enabled` together, because the surround cannot read another
  release's replica count (`05-app-contract.md`). This fixes a live bug:
  `pdb.grist.minAvailable: 1` and `pdb.keycloak.minAvailable: 1` sit against
  `replicaCount: 1`, safe today only because HPA `minReplicas: 2` is on by default. Turn HPA
  off and node drains hang forever.
- **One shared Gateway per environment** in an infra namespace; apps attach via HTTPRoute
  with `allowedRoutes.namespaces.selector`. LiveKit is the documented exception.
- **CRDs managed explicitly** — a dedicated `10-crds` Kustomization reconciled first. Helm
  does not upgrade CRDs; the silent failure is the new field being ignored.
- **Ordering declared, not assumed** — operators before CRs, Keycloak before clients, CNPG
  before Databases. Flux `dependsOn` with health checks.
- **`topologySpreadConstraints` in the base**, or the PDB is a lie when three replicas land
  on one node.
- **PriorityClasses** so gateway, Keycloak and operators evict last.
- **Default-deny NetworkPolicy** with declared egress, from `platform-app`. The old repo's
  per-app `networkPolicy.extraEgress` blocks are the real egress graph (`09-harvest.md`).
- **Security context defaults** applied by Kyverno mutation to every pod, ours or upstream's
  — but only the portable half: `capabilities: drop [ALL]`, `allowPrivilegeEscalation: false`,
  `seccompProfile: RuntimeDefault`. `runAsUser` and `readOnlyRootFilesystem` are **validated,
  not mutated**, because they are image-specific and mutating them cluster-wide breaks
  upstream images that run as a different UID or write to their own filesystem. `adr/0013`
- **No `kubectl apply` in prod**, enforced by RBAC not convention.
- **Service-to-service auth is Keycloak client credentials**, not a mesh.
