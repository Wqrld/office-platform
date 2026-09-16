# ADR-0012: Consume upstream charts; build the surround

## Status
**Accepted.** Supersedes the "spike at M4" proposal, and amends ADR-0002.

## Context
The original design assumed we would author charts for most applications, because
"La Suite's charts are thin or absent." That was wrong, and the correction is large enough
to change the architecture.

Verified chart availability, September 2026:

| App | Upstream chart | Latest | Verdict |
|---|---|---|---|
| Docs | `suitenumerique.github.io/docs` | 5.5.0, 2026-08-24 | Active |
| Drive | `suitenumerique.github.io/drive` | 0.21.2, 2026-08-25 | Active |
| Meet | `suitenumerique.github.io/meet` | 0.0.27, 2026-07-21 | Active |
| Conversations | `suitenumerique.github.io/conversations` | 0.0.7 | Exists, early |
| Find | `suitenumerique.github.io/find` | 0.0.3 | Exists, early, known Job bug |
| People | `suitenumerique.github.io/people` (chart `desk`) | 0.0.7, **2025-04-04** | **Stale — 17 months** |
| Keycloak | Keycloak Operator | — | Official |
| LiveKit, OpenSearch, Collabora, Ollama, Grist | vendor / community | — | Available |
| **Calendars** | **none** | — | We template it |
| **Bureaublad** | **none** (our own application) | — | We template it |
| Element | `element-hq/ess-helm` matrix-stack | — | Available, AGPL-3.0 |

Twelve of the fourteen applications have a usable upstream chart, Element included
(OpenSearch appears in the table as a shared datastore, not an application). Authoring our
own would duplicate work
DINUM does continuously, on applications they wrote — and `lasuite-platform` demonstrates
the whole suite deploying in ~5,000 lines by consuming them.

## Decision
Consume upstream charts. Build the **surround** — routes, network policy, disruption budget,
observability, secret wiring — as `platform-app`, attaching to upstream workloads by label
(`04-platform-charts.md`).

Author charts only for Calendars and Bureaublad.

Apply platform invariants through Kyverno rather than through chart templates (`adr/0013`),
because template-based enforcement only reaches charts we template, which is now two.

**Per-app values discipline**, from problems already observed:

- Always pin `image.tag`. Every La Suite chart declares `appVersion: latest` and defaults the
  tag to `latest`. Chart version and image version are separate pins; Meet's differ entirely
  (chart 0.0.x, app v1.x).
- Disable the chart's Ingress objects; we emit HTTPRoutes (ADR-0006).
- Disable the chart's own PodDisruptionBudget, ServiceMonitor, HPA and NetworkPolicy where it
  has them. The surround owns those, and two PDBs over the same pods is a node drain that
  never completes.
- `install.disableWaitForJobs` and `upgrade.disableWaitForJobs` on every release — upstream
  Jobs use short `ttlSecondsAfterFinished`. (Those are the Flux field names; `waitForJobs` is
  not a key.) Accept the consequence: Flux reports Ready before migrations finish.
- `upgrade.remediation.retries: 0` on anything that migrates a database. A Helm rollback
  reverts code and not schema.
- Consume every secret by `envFrom`; never inline a value the chart would then hold in its
  release data.

## Consequences

**The saving.** Roughly 21,800 lines of planned chart authoring becomes ~1,200 lines of
platform charts plus two ~40-line app charts. Docs goes from a planned ~80-line tier-4 chart
plus config to ~70 lines of config and no chart at all.

**The dependency.** We now depend on DINUM's release cadence and their values-schema
stability. This is a real transfer of control and the honest reason to hesitate. Three things
make it acceptable:

1. Render-diff on every version bump shows exactly what changes before merge, and the
   **binding check** catches the failure render-diff cannot see — an upstream rename that
   silently unhooks our routes, policies and alerts (`10-verification.md`). Together they are
   the practice that makes consuming someone else's chart safe; render-diff alone is not.
2. `postRenderers.kustomize.patches` handles a broken release without a fork, per app,
   visibly.
3. Vendoring one chart later is a per-app decision costing days, not an architecture change.
   The reverse — discovering at M6 that fourteen hand-written charts must track upstream
   forever — costs months.

**Uneven quality is priced in.** Find's migrate Job has an immutable name that breaks every
upgrade. People's `desk` chart templates its `createsuperuser` command as a string and
Kubernetes rejects it. Both are `known-limitations.md` entries with workarounds, not reasons
to write fourteen charts.

**People is in scope** (the user asked for it if usable). It is usable with two known bugs
and a stale chart; scheduled at M6 with the superuser created by our own Job. If the chart
stays unmaintained, it becomes our third `mb-*` chart — the app is wanted, the chart is
replaceable.

**Element is in scope and also upstream.** An earlier draft of this ADR stated that
`element-hq/ess-helm` was "licensed for non-commercial deployments up to 100 users" and
treated that as disqualifying. That was wrong on both counts.

ESS Community is **AGPL-3.0** — no restriction on commercial use and none on user count. The
"small-/mid-scale, non-commercial community use cases with up to 100 users" line is Element's
README describing who they built it for and where ESS Pro takes over. It is positioning, not
a licence term.

So `element-hq/ess-helm` joins the consume-upstream list — Synapse with workers, Matrix
Authentication Service, Element Web and Admin, Matrix RTC — and Element stops being the
largest chart we would have owned. What remains for M8 is a support and scaling question, not
a legal one, plus mild AGPL obligations that only bite if we modify it. Synapse has been
AGPL-3.0 since 2023 regardless, and EUPL-1.2 lists AGPL-3.0 as compatible.

The same draft justified dropping Matrix on the grounds that "Conversations already covers
team chat". It does not: Conversations is an LLM assistant. Element is the suite's only
messenger. See `08-app-inventory.md`.

## What survives from ADR-0002

Its reasoning about collapsing 160 near-identical templates was correct for a world where we
wrote them. We no longer do — DINUM absorbed that duplication upstream. The library chart
survives at ~250 lines serving four consumers, and the *surround* it now provides is the
more durable half: routes, policy, observability and disruption budget around a workload,
which is exactly what makes a third-party chart safe to adopt.
