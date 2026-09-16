# 04 — The platform charts

**Revised.** The first draft made `platform-lib` a workload-generating library chart, on the
belief that we would author charts for most apps. We won't: 12 of the 14 apps have a maintained
upstream chart (`adr/0012`). What we build is the *surround*.

## The four things we ship

| Chart | Purpose | Rough size |
|---|---|---|
| **`platform-app`** | The surround: routes, network policy, disruption budget, observability, secret wiring — around a workload someone else's chart created | ~400 lines |
| **`platform-deps`** | Everything an app must have before it starts: Postgres / cache / object store / search, managed or external, plus the OIDC and service-token Secrets — all normalised to one secret shape | ~400 lines |
| **`platform-infra`** | Cluster singletons: the shared Gateway, PriorityClasses, ClusterIssuer | ~150 lines |
| **`platform-lib`** | Small library of helpers shared by the above and by our own two app charts | ~250 lines |

Plus **`mb-calendars`** and **`mb-bureaublad`**, the only two applications with no upstream
chart, each built on `platform-lib`.

And **`policy/`** — Kyverno policies, which are now where platform invariants live
(`adr/0013`). This is the part that replaces what the library chart was going to enforce.

## `platform-app` — the surround

It creates nothing that runs. It creates everything *around* what runs, for a workload
deployed by a chart we do not own.

```yaml
# config/apps/docs.yaml — the surround release
target:
  release: docs                    # the upstream HelmRelease it wraps
  components:                      # Services for routing, pod labels for policy
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
  - {host: docs, component: backend,   path: /media, maxBodySize: 1Gi}
  - {host: docs, component: yprovider, path: /collaboration/ws, websocket: true}

egress:
  - {datastore: postgres}
  - {datastore: cache}
  - {datastore: objectstore}
  - {app: collabora, port: 9980}
  - {external: true, port: 443}

pdb:      {enabled: true}          # set by the size profile, alongside replicas
metrics:  {enabled: true, port: 9100}
extraObjects: []
```

Emits: HTTPRoutes, default-deny NetworkPolicy plus declared egress, PodDisruptionBudgets,
ServiceMonitor, PrometheusRule, and the Envoy Gateway traffic policies the routes imply.

**A component is two different things, and conflating them is the first bug.** An HTTPRoute
`backendRef` names a **Service and a port**; a NetworkPolicy, a PDB and a ServiceMonitor take
a **label selector**. The upstream chart owns both, and its service names are not derivable
from its component labels. So `components` carries both, explicitly — and that is the price
of attaching to someone else's chart rather than generating the workload.

**Why a selector and not a template.** The surround attaches to what upstream created rather
than generating it, so it works against any chart, including ones whose internals change
between versions.

**The failure mode this creates, and how it is caught.** If an upstream bump renames a Service
or a component label, our selectors silently match nothing: no route backend, a PDB protecting
zero pods, a ServiceMonitor scraping nothing — none of which fails a Helm install. Render-diff
does not catch it either, because our release did not change. So CI runs a **binding check**:
render the upstream release and the surround together, and assert that every declared
`service.name` exists with that port and every `selector` matches at least one pod template.
Ten lines of `yq`, and it is the single most valuable test in `10-verification.md`.

**Routes need more than an HTTPRoute.** The websocket timeout on `/collaboration/ws` and the
body-size allowance on `/media` are not HTTPRoute fields. HTTPRoute carries
`timeouts.request`/`timeouts.backendRequest`; Envoy's stream and connection idle timeouts and
its buffer limits come from Envoy Gateway's `ClientTrafficPolicy` and `BackendTrafficPolicy`.
`platform-app` emits those from `websocket: true` and `maxBodySize:` so no app file has to
know the CRD — confirm the exact field names against the Envoy Gateway version pinned at M1.

## `platform-lib` — what survives

Much smaller than planned, and used in three places: by `platform-app`, by
`platform-deps`, and by our own two app charts.

| Helper | Used by |
|---|---|
| `platform.names`, `platform.labels`, `platform.selector` | all |
| `platform.httproute` | `platform-app` |
| `platform.networkpolicy` — resolves `datastore:` / `app:` / `external:` | `platform-app` |
| `platform.pdb` — guarded on replicas > 1, always `maxUnavailable` | `platform-app` |
| `platform.observability` | `platform-app` |
| `platform.oidc` — the OIDC env block, internal/external URL split | app values, both own charts |
| `platform.workload` | `mb-calendars`, `mb-bureaublad` only |
| `platform.jobs` | own charts only |

`platform.workload` and `platform.jobs` survive because Calendars and Bureaublad need them —
but they are no longer the centre of the design, and they serve two consumers instead of
fourteen. If a third app ever needs its own chart, they are already there.

## Invariants move to Kyverno

The first draft enforced the security baseline, labels and topology spread through library
templates. That only works for charts we template — which is now two.

**Kyverno mutation policies apply them to everything**: upstream app charts, operators,
datastores, the gateway. Strictly better coverage than the library chart ever offered, and
the reason the redesign does not cost us the invariants. Details and the honest cost in
`adr/0013`.

| Invariant | Mechanism |
|---|---|
| Namespace baseline | Pod Security Admission `restricted` |
| `capabilities: drop [ALL]`, no privilege escalation, `seccompProfile` | Kyverno **mutate** |
| Required labels | Kyverno **mutate** |
| `topologySpreadConstraints` when replicas > 1 | Kyverno **mutate** |
| `runAsUser` non-zero, `readOnlyRootFilesystem` | chart values; Kyverno **validate** (audit → deny) |
| No `minAvailable` PDB on a single replica | `platform-app` + CI; Kyverno validate as backstop |
| Resources set | Kyverno **validate** (audit → enforce) |
| Image registry allowlist, no floating tags | Kyverno **validate** (deny) |

`runAsUser` and `readOnlyRootFilesystem` are deliberately *not* mutated cluster-wide: the
pods here are Keycloak's, CNPG's, Garage's, OpenSearch's and DINUM's, built for their own
UIDs. `adr/0013` explains why the mutation the first draft proposed would have broken a fresh
bootstrap.

Known exceptions — Collabora, and Calendars' CalDAV container at `runAsUser: 33` with a
writable root filesystem — are policy exclusions, declared once, in the policy, where they
are visible rather than buried in an app's values.

## Jobs and migrations

Upstream charts ship their own migration Jobs, so this is no longer ours to build for most
apps. Two things remain ours:

- **Our own two charts** use `platform.jobs`: Helm hooks with
  `hook-delete-policy: before-hook-creation`, no timestamp-suffixed names.
- **Upstream Job bugs** are handled per app in `known-limitations.md` and, where necessary,
  with a `postRenderers.kustomize.patches` entry. Find's chart is the live example: it names
  its migrate Job `find-backend-migrate-{chartVersion}` and the chart version rarely moves, so
  the immutable `spec.template` breaks every upgrade (`08-app-inventory.md`).

Set `install.disableWaitForJobs` and `upgrade.disableWaitForJobs` on every HelmRelease —
upstream Jobs use short `ttlSecondsAfterFinished` values and Helm's wait races against
garbage collection. (These are the Flux field names; there is no `waitForJobs` key.)

The consequence must be stated rather than discovered: **Flux then reports a release Ready
before its migration Job has finished**, so `dependsOn` no longer gates on migrations. Where
an app genuinely must not start against an unmigrated schema, that is the upstream chart's
init-container problem, not something `dependsOn` can fix for us.

**Never auto-rollback an app that migrates a database.** Set
`upgrade.remediation.retries: 0` on every release with a migration Job. A Helm rollback
reverts the code and not the schema, which is how a failed upgrade becomes an outage.

## What we deliberately do not do

- **No re-modelling of Kubernetes APIs** (P2). The upstream charts have their own values
  schemas; we pass them through and do not wrap them.
- **No duplicate objects.** Most upstream charts can also emit a PDB, a ServiceMonitor, an
  HPA and sometimes a NetworkPolicy. Every app file turns those off explicitly — two objects
  selecting the same pods is a PDB that blocks drains and a metric counted twice. This is
  part of the per-app values discipline in `adr/0012`, and the binding check asserts it.
- **No vendoring of upstream charts.** Pin a version, render-diff the bump. If a chart needs a
  patch, `postRenderers` — visible, per-release, and per `adr/0012` a per-app decision rather
  than an architectural one.
- **No branching on datastore kind** in the surround. Separate release (P4).
