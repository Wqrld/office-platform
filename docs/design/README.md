# Platform design

Design set for the successor to `mijn-bureau-infra`. Written to be implemented from,
not admired.

**Implementing this? Read [`00-start-here.md`](00-start-here.md).** It is the handoff brief —
what you are building, the six principles, fourteen defaults that are wrong here,
and M1 concretely. It is also the file to hand an agent that has never seen this repository.

**Deciding on it?** Read `01-decision.md` first; everything else assumes that decision is
made.

## The short version

Rebuild in a fresh pair of repos on a **consume-upstream-charts + Flux** architecture.
Harvest the integration knowledge from `mijn-bureau-infra` — substantial and hard-won — and
leave its structure behind.

Measured, on the 15 application directories we keep from the old repo (Nextcloud and
OpenProject dropped). The new platform runs **14 applications** — ClamAV deferred, People
added (`08`):

| | now | after |
|---|---:|---:|
| Authored lines | ~105,000 | **~4,000** + ~1,600 of platform charts and policy |
| Helm charts we maintain | 23 | **2** |
| Vendored Grafana dashboard JSON | 47,885 | ~0 |
| Cost of adding an application | 6,000–9,000 lines, ~15 files touched | **25–85 lines, 1 file** |

The step change came from a fact we did not have at first: **DINUM actively maintains Helm
charts for Docs, Drive, Meet, Conversations, Find and People**, and vendor or community
charts exist for everything else except Calendars and Bureaublad. We consume those and build
the *surround* — routes, network policy, disruption budgets, observability — plus Kyverno for
platform invariants. See `adr/0012` and `adr/0013`.

## How to read this

| File | What it settles |
|---|---|
| `00-start-here.md` | **The implementation brief. Start here to build.** |
| `01-decision.md` | Continue vs. restart, with the measurements behind it |
| `02-architecture.md` | Principles, stack, and where the original proposal needed correcting |
| `03-repo-layout.md` | The two repos, concretely |
| `04-platform-charts.md` | The four charts we ship — the surround and the prerequisites, not the workloads |
| `05-app-contract.md` | What an app file looks like, the tiers, sizing 5→5,000 |
| `06-datastores.md` | Postgres / cache / object storage / search contracts |
| `07-identity-and-secrets.md` | Keycloak, OIDC per app, and killing `derivePassword` |
| `08-app-inventory.md` | What the 14 apps actually are. **The highest-value file here.** |
| `09-harvest.md` | Exact paths to lift — from the old repo, and from `lasuite-platform` |
| `10-verification.md` | What catches which bug, and when: CI, render-diff, binding check, upgrade and auth tests, restore rehearsal |
| `11-roadmap.md` | Build order and milestones |
| `adr/` | One decision per file, a few paragraphs each |

## Settled

Consume upstream charts; write only Calendars and Bureaublad (`adr/0012`) · invariants in
Kyverno (`adr/0013`) · Garage via `garage-operator`, external S3 first-class (`adr/0009`) ·
one shared CloudNativePG cluster (`06`) · single-tenant with tenant-qualified names
(`adr/0008`) · **People in scope at M6** · **Element in scope at M8** on Element's own ESS
chart · ClamAV deferred.

**Open:** the Matrix web client (`adr/0011`, decide at M8) — ESS bundles Element Web, so
keeping it is the zero-work default.

**Corrected:** an earlier draft claimed Element Server Suite was licence-restricted to
non-commercial use under 100 users and recommended dropping Matrix. ESS is **AGPL-3.0** — no
commercial or user-count restriction; the 100-user figure is Element's positioning for where
ESS Pro takes over. And **Conversations is an LLM assistant, not team chat**, so Element is
the suite's only messenger. Matrix stays.

**Corrected in the implementation-readiness pass**, all in the direction of "this would not
have worked as written":

- The surround's `components` map needs **Service names *and* pod labels** — an HTTPRoute
  backend is a Service, a NetworkPolicy is a selector (`04`). And because the surround
  selects into someone else's release, an upstream rename is invisible to render-diff, so
  CI gains a **binding check** (`10`).
- **Secrets cannot come from the surround** — it runs after the app that must read them. The
  first release is now prerequisites: datastores *and* the OIDC Secret (`05`, `07`).
- **Kyverno must not mutate `runAsUser: 1001` / `readOnlyRootFilesystem` cluster-wide.** That
  default came from Bitnami images in charts we templated; applied to Keycloak, CNPG, Garage,
  OpenSearch and DINUM's images it breaks a fresh bootstrap. Mutate the portable settings,
  validate the rest, and let PSA `restricted` be the baseline (`adr/0013`).
- **Size profiles are one file each, not one patch each.** The upstream charts do not
  share a values schema, and a strategic-merge patch on a path a chart lacks is a silent
  no-op (`05`).
- **Two shared Valkey instances, not one** — eviction policy is per instance, and an evicting
  Celery broker drops tasks (`06`).
- The OpenSearch contract promised per-app credentials while the inherited configuration
  disables the security plugin entirely. Pick one, at M6 (`06`).
- **14 applications**, not 15: ClamAV out, People in (`08`).
- `platform-datastore` is renamed **`platform-deps`** — it owns the datastores *and* the
  OIDC and service-token Secrets, because those must exist before the workload starts.
- Per-bucket **lifecycle and retention ownership** is recorded per app; the datastore
  contract creates a bucket and a quota and decides nothing about what is ever deleted
  (`06`, `10`).

## Goals, in priority order

1. **Maintainable by a small team over years.** One person must be able to read the config
   repo and know what runs.
2. **Concise.** Adding an app is a file, not a project. Platform-wide changes are one diff.
3. **Runnable by organisations of 5 to 5,000 people.** One set of app files, three size
   profiles (`05`). Single-tenancy per cluster; multi-tenancy must not be designed *out*.
4. **Current.** The base tracks upstream automatically in dev, deliberately in prod.

## Non-goals

- A general-purpose PaaS. This runs *these* applications.
- Multi-cloud portability.
- Service mesh.
- Preserving compatibility with the existing `helmfile` repo. It is a source of knowledge,
  not a migration source.
