# 11 — Build order

Sequenced so the riskiest assumption is tested first and every milestone ends with something
running. No time estimates — they would be invented. The exit criteria are real.

## M0 — Decisions (done)

All four are settled. Recorded here because the reasoning matters more than the answer.

| Question | Decision | ADR |
|---|---|---|
| Object storage | **Garage** via `garage-operator`; external S3 a first-class mode | `0009` |
| Postgres topology | **One shared CNPG Cluster**, `Database` + `Role` per app, one PgBouncer `Pooler` | `06-datastores.md` |
| Tenancy | Ship single-tenant; `${TENANT}` in every name from day one | `0008` |
| Element / ClamAV | **Element in scope at M8**, on Element's own ESS chart (AGPL-3.0; the "100 users" line is positioning, not a licence term). **ClamAV deferred** | `08-app-inventory.md` |
| App charts | **Consume upstream; write only Calendars and Bureaublad.** Invariants move to Kyverno | `0012`, `0013` |
| People | **In scope at M6**, upstream chart with two documented defects | `08-app-inventory.md` |

**One decision with an early deadline despite its milestone being last:** `matrixDomain` can
only be set once at setup and is permanent. Settle it before the first production install,
not at M8.

**One decision deliberately left open:** the Matrix web client (`adr/0011`). It gates nothing
before M8 and the information improves with waiting.

## M1 — Skeleton

Two repos, CI, and an empty cluster that reconciles.

- `platform` and `config` repos, EUPL-1.2, CI from `10-verification.md`
- `platform-infra`: the shared Gateway, PriorityClasses, ClusterIssuer
- `config/clusters/dev`: Flux bootstrap, the four Kustomizations, `vars.yaml` with
  `${BASE_DOMAIN}`, `${STORAGE_CLASS}`, `${TENANT}`
- `config/infra`: cert-manager, Envoy Gateway, ESO, CNPG, garage-operator, Kyverno (audit),
  kube-prometheus-stack — note garage-operator's webhooks need cert-manager reconciled first
- OCI release pipeline: tag → `helm push` → cosign sign
- cert-manager `ClusterIssuer` and the certificate strategy: a wildcard for `*.<domain>` or
  per-host certificates, and DNS-01 either way — LiveKit's `turn-livekit` certificate cannot
  use HTTP-01 because it sits on a UDP LoadBalancer outside the Gateway
- Pod Security Admission labels on the namespace template (`adr/0013`)

**Done when:** `flux bootstrap` on a kind cluster brings up the operators and the Gateway
gets a certificate, from nothing, in CI.

## M2 — Identity and secrets

The two things everything else depends on. Getting secrets right here is what stops
`derivePassword` reappearing by convenience.

- ESO with a SOPS/age bootstrap root; generate-once credential flow
- Keycloak Operator, Keycloak CR, its CNPG database
- Realm harvested from `apps/keycloak/keycloak.yaml.gotmpl`, ten clients, secrets via ESO
- The `platform.oidc` library helper producing the 22-variable env block

**Done when:** a throwaway test client completes an OIDC login against the realm, and no
credential exists in git except the SOPS-encrypted bootstrap roots.

Keep that login as the **auth smoke test** (`10-verification.md`) — a permanent nightly job
from here on, not a milestone gate. It is the only thing that catches the internal/external
token-exchange failure, and gitleaks in CI is what keeps the second half of this criterion
true after today.

## M3 — `platform-deps`

- Canonical secret shapes for postgres / valkey / objectstore / opensearch
- `mode: managed` and `mode: external` for all four, with `egressCIDR` schema-required
  when external
- Shared CNPG `Cluster` + PgBouncer `Pooler`, `Database` + `Role` per app with no
  cross-database grants
- Two shared Valkey instances — evicting cache, non-evicting broker (`06-datastores.md`);
  shared `GarageCluster` with per-app `GarageBucket` + `GarageKey`
- Two CNPG `Pooler`s: transaction mode for apps, session mode for migrations
- Preflight Job; wait-init-container

**Done when:** Grist — one workload, three datastores — runs end to end with a byte-identical
app file in **both** managed and external mode, for **both** Postgres and object storage.
Prove external mode now; retrofitting it later is the expensive version — then put it in the
**nightly rotation**, because a mode proven once and never exercised again is a claim rather
than a feature (`10-verification.md`).

## M4 — `platform-app`, proven against Docs

**The pivotal milestone**, unchanged in position and changed in content. Docs is still the
hardest app — five workloads, five routes including a websocket, three datastores, three
cross-app integrations — but we now deploy DINUM's chart and build the surround.

- Upstream Docs chart at a pinned version and a pinned **image tag** (the chart defaults to
  `latest`), with all five of its Ingress objects disabled
- `platform-app`: HTTPRoutes including the websocket timeout, default-deny NetworkPolicy
  plus declared egress, PDBs, ServiceMonitor, PrometheusRule
- `platform-lib` helpers it needs; `platform.oidc` emitting the internal/external URL split
  as a Secret consumed via `envFrom`
- The **binding check** (`10-verification.md`) — build it here, with the first surround, not
  after the fifth app
- Kyverno mutate policies live in audit, and render-diff running `kyverno apply`

**Done when:** Docs runs from ~85 lines of config and **no chart of our own**, and the
binding check is green.

`postRenderers` entries are expected here, not disqualifying — `08-app-inventory.md` already
names upstream defects that need them. Each is logged in `known-limitations.md` with what
would remove it, and the *count* is the metric: one is normal, three means the surround is
missing a feature (P5).

## M5 — The rest of the upstream apps

drive · meet · conversations · grist · collabora · ollama · livekit

These should now be mechanical: add the Helm repository, pin chart and image, disable
ingress, write the surround. Any app needing a `platform-app` change is a finding worth
recording.

Notes: Meet's chart version does not track its app version, and its realtime agents need a
paid external STT API — keep them at zero replicas. LiveKit stays outside the shared Gateway
with a UDP LoadBalancer; TURN/UDP only, no TURN certificate (adr/0105). **Meet and LiveKit
are done** (`config/apps/{meet,livekit}/README.md`), transcripts included, via a self-hosted
whisperx on CPU; no `platform-app` change was needed, two `postRenderers` were.

**Done when:** each app is under 70 lines in one file, and adding one is a single-file PR.
Measure it — this number is the whole justification for the rebuild.

## M6 — The apps we write, and People

- **`mb-calendars`** — no upstream chart. Four workloads, the CalDAV security-context
  exception, and net-new Gateway API routing (it never left Ingress).
- **`mb-bureaublad`** — our own portal application.
- **People** — upstream `desk` chart with its two known defects worked around
  (`08-app-inventory.md`).
- **Find** — ✅ **done**. Upstream chart, plus the two traps: a request without
  `X-Forwarded-Proto` forces indexation through the external URL (`08-app-inventory.md`, as
  corrected), and the migrate Job's immutable name breaks every upgrade.

  Two things found on the way that the design set did not anticipate: upstream has **never
  cut a release** — zero tags — so Find is pinned to a commit, the one departure from
  `adr/0104`; and hybrid/semantic search no longer exists upstream, so only
  `flag_find_full_text_search` is set. See `config/apps/find/README.md`.
- **Decide the OpenSearch security posture** — ✅ **decided: plugin on**, per-app internal
  user and a role scoped to the app's index prefix. Recorded as `adr/0111`. The deciding
  argument was that this cluster enforces no NetworkPolicy (`adr/0103`), so the "off and
  documented as unauthenticated" option had nothing behind it.

**Done when:** full-text search works from Docs through Find with the index created by a Job;
Calendars and Bureaublad run from ~40-line charts on `platform-lib`.

## M7 — Production readiness

- Kyverno promoted from audit to enforce, with `kyverno test` fixtures per rule — both
  directions, and the documented exclusions asserted as excluded
- The **upgrade test** green nightly, and running on every Renovate bump PR
- Backups: CNPG → object storage; object-store replication; the recovery inventory file,
  including per-bucket lifecycle and retention ownership
- **Restore rehearsal, timed** — the real RTO number
- Generated ServiceMonitors, PrometheusRules and dashboard references; delete the vendored JSON
- `config/clusters/prod` with pinned OCI versions and Renovate opening bump PRs
- Nightly bootstrap-from-scratch green

**Done when:** a restore into a scratch namespace has been done and timed, and prod pins are
under Renovate.

## M8 — Matrix

Element/Synapse, on Element's own `element-hq/ess-helm` `matrix-stack` chart — Synapse with
workers, Matrix Authentication Service, Element Web and Admin, and Matrix RTC. AGPL-3.0, so
commercial use and any user count are permitted (`08-app-inventory.md`).

- Deploy ESS as a consume-upstream release with the platform surround
- **Keycloak integration goes through MAS**, not through Synapse's own OIDC. The old repo's
  `synapse` client is not a usable template — build an MAS-shaped client instead
- `.well-known` delegation on the `matrix` hostname
- Decide the web client per `adr/0011` — ESS bundles Element Web, so keeping it is the
  zero-work default and a swap is now a deliberate cost

Scheduled last because nothing depends on it and it is the app whose behaviour is dominated
by Matrix rather than by our platform.

**Two things to verify here rather than assume:** whether the Community chart's defaults
carry your largest deployment (Element positions ESS Pro above ~100 users, and that is a
support and scaling claim, not a permission one), and that AGPL obligations stay mild — they
do if we deploy it unmodified.

**Done when:** Element runs against the realm via MAS, `matrixDomain` is recorded as
permanent, and `adr/0011` is Accepted rather than Proposed.

---

## Ordering rules

1. **Docs before the easy apps.** Proving the surround against three simple apps and then
   meeting Docs is how `platform-app` acquires a second, incompatible shape.
2. **Secrets before apps.** Every app added under a temporary secret scheme is an app to
   migrate later.
3. **Render-diff and the binding check before the second app.** Their value is proportional
   to the number of consumers; their cost is a day each. Have them before they are needed.
4. **The upgrade test as soon as there is something to upgrade.** Every failure we already
   know about is an upgrade failure, and bootstrap-from-scratch cannot see any of them
   (`10-verification.md`). It is one extra step on a cluster the nightly already builds.
5. **One escape hatch is a signal, three are a feature.** Track every use of `extraObjects`
   and `postRenderers`; when a pattern hits three, promote it into the library (P5).

## What "done" looks like

- Adding an application is one file and 25–70 lines.
- A `platform-app` bump is one PR against `config` showing a rendered diff across every app.
- An upstream chart bump is one PR affecting exactly one app.
- The same app files run at 5 people and 5,000, differing by one size overlay.
- An empty cluster reaches a working platform from `flux bootstrap` plus one key.
- The RTO is a measured number, not an estimate.
- An upstream chart bump is answered by CI — rendered diff, binding check and a real upgrade
  on a real cluster — rather than by deploying it and watching.
- No secret in git except the SOPS-encrypted bootstrap roots.
