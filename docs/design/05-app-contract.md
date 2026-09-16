# 05 — The app contract

**Revised** alongside `04`. An application is now normally three HelmReleases in one file, in
this order: its prerequisites (datastores and secrets), the upstream chart, and our surround.

## The shape

`config/apps/docs.yaml`, complete and realistic:

```yaml
# ── 1. prerequisites — datastores, OIDC secret, service tokens ─
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: {name: docs-deps, namespace: docs}
spec:
  interval: 30m
  dependsOn: [{name: keycloak, namespace: identity}]
  chartRef: {kind: OCIRepository, name: platform-deps, namespace: flux-system}
  values:
    postgres:    {mode: managed, database: docs, extensions: [pg_trgm, unaccent]}
    cache:       {mode: managed, uses: [cache, broker]}
    objectstore: {mode: managed, bucket: docs, quota: {maxSize: 200Gi}}
    oidc:        {client: docs}          # emits Secret docs-oidc: the 22 OIDC_* vars
---
# ── 2. the application, from DINUM's chart ───────────────────
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: {name: docs, namespace: docs}
spec:
  interval: 30m
  dependsOn: [{name: docs-deps}]
  install: {disableWaitForJobs: true}
  upgrade: {disableWaitForJobs: true, remediation: {retries: 0}}
  chart:
    spec:
      chart: docs
      version: "5.5.0"                      # pinned in prod, semver range in dev
      sourceRef: {kind: HelmRepository, name: suitenumerique-docs, namespace: flux-system}
  values:
    image: {tag: v5.5.0}                    # chart defaults to `latest` — always pin
    ingress:                  {enabled: false}   # we emit HTTPRoutes instead
    ingressAdmin:             {enabled: false}
    ingressMedia:             {enabled: false}
    ingressCollaborationApi:  {enabled: false}
    ingressCollaborationWS:   {enabled: false}
    backend:
      podDisruptionBudget: {enabled: false}      # the surround owns PDBs
      serviceMonitor:      {enabled: false}      # the surround owns observability
      envVarsFrom:                               # every secret is consumed, never inlined
        - {secretRef: {name: docs-oidc}}
        - {secretRef: {name: docs-postgres}}
        - {secretRef: {name: docs-cache}}
        - {secretRef: {name: docs-s3}}
---
# ── 3. the surround ──────────────────────────────────────────
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: {name: docs-platform, namespace: docs}
spec:
  interval: 30m
  dependsOn: [{name: docs}]
  chartRef: {kind: OCIRepository, name: platform-app, namespace: flux-system}
  values:
    target:
      release: docs
      components:                              # Services for routes, labels for policy
        backend:
          service:  {name: docs-backend, port: 8000}
          selector: {app.kubernetes.io/component: backend}
        frontend:
          service:  {name: docs-frontend, port: 8080}
          selector: {app.kubernetes.io/component: frontend}
        yprovider:
          service:  {name: docs-y-provider, port: 4444}
          selector: {app.kubernetes.io/component: y-provider}
    routes:
      - {host: docs, component: frontend,  path: /}
      - {host: docs, component: backend,   path: /api}
      - {host: docs, component: backend,   path: /admin}
      - {host: docs, component: backend,   path: /media,  maxBodySize: 1Gi}
      - {host: docs, component: yprovider, path: /collaboration/ws, websocket: true}
    egress:
      - {datastore: postgres}
      - {datastore: cache}
      - {datastore: objectstore}
      - {app: collabora, port: 9980}
      - {external: true, port: 443}
    pdb:     {enabled: true}                   # set by the size profile, with replicas
    metrics: {enabled: true}
```

**~85 lines for the hardest app in the suite**, of which ~15 are the boilerplate that turns
off the upstream chart's own ingress, PDB and ServiceMonitor. The same app is 15,022 lines
today. A simple app — Grist, Collabora, Ollama — is 25 to 40.

### Three releases, and why the order is what it is

**Secrets must exist before the workload that consumes them, so they cannot come from the
surround.** The surround runs *after* the app — it attaches to workloads the app created —
so everything the app must read at startup (datastore secrets, the OIDC env block, service
tokens) belongs in release 1. `platform-deps` therefore owns secret production as well as
datastores — which is why it is named for the role rather than for the kind — and
`platform-app` owns only objects that reference an existing workload.

**The OIDC block is delivered as a Secret, not as a Helm helper.** `platform.oidc` is a
`platform-lib` helper, and a library helper cannot reach inside DINUM's chart. So it renders
a Secret in release 1, and the app consumes it through whatever the upstream chart calls
`envFrom` (`envVarsFrom` in the La Suite charts). Anything the upstream chart cannot consume
by `envFrom` is a `postRenderers` entry — a per-app finding, logged (`10-verification.md`).

**The NetworkPolicy arrives after the pods are already running**, because it is in release 3.
That is the right trade — a wrong egress rule cannot block a rollout — but it means
default-deny is not in force during the first reconcile of a fresh namespace. If that matters
for a given environment, put a namespace-wide default-deny in the `30-platform` layer and let
the surround add only the allow-rules.


## Where each concern lives

| Concern | Owner |
|---|---|
| Workload shape, container args, probes, upstream env vars | **the upstream chart** |
| Which version, which image tag, app-specific values | `config/apps/<name>.yaml` |
| Databases, cache, buckets, search, and their secrets | `platform-deps` |
| Routes, network policy, PDB, metrics, alerts | `platform-app` |
| Security context, labels, topology spread, resource rules | **Kyverno** (`adr/0013`) |
| Per-environment size and replica counts | `overlays/size-*.yaml` (below) |
| Which apps a given cluster runs at all | `clusters/<env>/40-apps.yaml` (`03-repo-layout.md`) |

Nothing is in two places. That is the property worth protecting when this gets edited a year
from now.

## Sizing: 5 to 5,000 people

One set of app files, three size profiles. This is the mechanism that has to carry the
stated range, so it is explicit rather than emergent — and it is worth being precise about,
because the obvious version does not work.

**One patch cannot target all fifteen apps.** A Kustomize patch with no name selector,
targeting `kind: HelmRelease`, applies the *same values path* to every release — but the
upstream charts do not share a values schema. Docs has `backend.replicaCount`, Meet has its
own shape, ESS has another, and a strategic-merge patch that sets a path a chart does not
have is a silent no-op. So the mechanism is:

| Layer | How the size profile reaches it |
|---|---|
| **Our charts** (`platform-app`, `platform-deps`, `mb-*`) | one genuinely app-agnostic patch — `pdb.enabled`, `metrics`, replica counts, all on a schema we own |
| **Upstream app charts** | one **file** per profile containing a small named patch per app, because each chart's replica/HPA path differs |
| **Scalars** (`${REPLICAS_WEB}`, `${PG_INSTANCES}`, `${STORAGE_CLASS}`) | `postBuild.substituteFrom` against the cluster's `vars.yaml` |

That is still *one file per profile* and no per-app-per-environment files, which is the
property worth protecting. It is not one patch, and claiming it is would set up the first
person who tries it to fail. Prefer the substitution route wherever a chart exposes the knob
as a plain scalar; fall back to a named patch only where it does not.

**`pdb.enabled` is set by the size profile, not inferred.** The surround cannot read the
upstream release's replica count — it is in a different HelmRelease's values — so "PDB only
when replicas > 1" is not something `platform-app` can decide on its own. The size profile
sets replicas and `pdb.enabled` together, in the same file, and CI asserts they agree by
rendering both releases (`10-verification.md`). Kyverno's PDB rule is the backstop, not the
mechanism.

| Profile | People | Shape |
|---|---|---|
| **`small`** | 5–50 | 1 replica everywhere, no PDBs, no HPA. CNPG single instance. One Garage node. OpenSearch single node or Find disabled. Runs on one modest node. |
| **`medium`** | 50–500 | 2 replicas for frontends and backends, HPA on, PDBs on. CNPG 2 instances + Pooler. Garage 3 nodes. |
| **`large`** | 500–5,000 | HPA everywhere with real ceilings, topology spread enforced, CNPG 3 instances + Pooler, Garage 3+ with a real replication factor, OpenSearch multi-node, LiveKit horizontally scaled. |

A cluster selects one in its `vars.yaml`. Moving between them is a patch swap, not an
app-file change — and because the upstream charts already expose replica and autoscaling
knobs that DINUM runs at scale, we are configuring their scaling rather than inventing ours.

The honest limit: `small` is genuinely small — one node, no HA, and a node reboot is
downtime. That is the correct trade for a 5-person deployment, but say so in the docs rather
than implying HA is free.

## The four tiers, revised

**Tier 1 — upstream chart plus surround.** The normal case. 12 of the 14 apps.

**Tier 2 — plus a datastore release.** Composition, not branching. Most of the 13.

**Tier 3 — escape hatch.** `extraObjects` in the surround, and
`postRenderers.kustomize.patches` on the upstream release for surgical fixes. Both live in
the same per-app file, next to what they apply to. Every use is logged in
`known-limitations.md` with what would remove it.

**Tier 4 — our own chart on `platform-lib`.** Only where no upstream chart exists: Calendars
and Bureaublad. If a third appears, the helpers are already there.

P5 still applies: used once, escape hatch; used three times, a feature.

## Adding an application

1. Add the Helm repository to `config/clusters/*/sources.yaml` (once per upstream).
2. Write `config/apps/<name>.yaml` — three releases, 25–70 lines.
3. Add it to `config/apps/kustomization.yaml`, and to each cluster that should run it.
4. Add the OIDC client to the realm (`07-identity-and-secrets.md`).
5. Add a line per size profile in `overlays/` if its replica knobs differ from the default.
6. Open a PR. CI renders, applies Kyverno mutations, and posts the diff.

If there is no upstream chart, step 2 is preceded by a ~40-line chart in `platform`.

## Version flow

Two independent streams now, which is a feature:

- **Upstream app charts** — pinned per app in `config`. Renovate opens a bump PR; CI shows
  the rendered diff for that one app. A DINUM release cannot break anything else.
- **Our platform charts** — `OCIRepository` with a semver range in dev, an exact tag in prod.
  A `platform-app` bump shows a rendered diff across every app before merge.

Never point prod at a semver range for either.
