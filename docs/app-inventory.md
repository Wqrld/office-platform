# Application inventory

What runs on this platform today, and what was surveyed for it. The per-app notes and the
upstream gotchas below were read out of the applications' repos, not assumed; the ones for
apps that run are also on the values they explain.

## Runs on this platform

`apps/<name>/` exists, the control plane knows it (`charts/control-plane/apps.yaml`), the
platform provisions for it (`charts/platform-tenants/values.yaml`).

| App | Workloads | PG | Cache | S3 | Search | OIDC | Chart | Hostname |
|---|---|:-:|:-:|:-:|:-:|:-:|---|---|
| **keycloak** | 1 (StatefulSet) | ● | | | | *is the IdP* | Operator | `id` |
| **docs** | 5 — backend, frontend, celery, yprovider, docspec | ● | ● | ● | ● | ● | upstream, git tag | `docs` |
| **drive** | 4 — backend, frontend, celery, celery-beat | ● | ● | ● | | ● | upstream, git tag | `drive` |
| **calendars** | 4 — backend, frontend, caldav, worker | ● | ● | | | ● | upstream PR, from our Helm repo | `calendars` |
| **projects** | 1 — backend (Sails: SPA, API, socket.io, files) | ● | ● | ● | | ● | ours in the app's repo, from our Helm repo | `projects` |
| **find** | 1 — backend | ● | ● | | ● | ● | upstream, commit pin | `find` |
| **meet** | 5 live (+4 at 0 replicas) + our whisperx | ● | ● | ● | | ● | upstream, git tag | `meet` |
| **livekit** | 2 — server, egress | | ● | | | | vendor, commit pin | `livekit`; `turn` → its own IP |
| **collabora** | 1 | | | | | | vendor | `collabora` |

The pins are in `charts/control-plane/templates/sources.yaml` and each `apps/*/release.yaml`.

## Surveyed, not running

| App | Workloads | PG | Cache | S3 | OIDC | Chart | Note |
|---|---|:-:|:-:|:-:|:-:|---|---|
| **element** | ESS stack — synapse, MAS, web, RTC | ● | ● | | ● | upstream ESS | `element`, `matrix` |
| **conversations** | 2 — backend, frontend | ● | ● | | ● | upstream 0.0.7 | an LLM assistant, not team chat |
| **bureaublad** | 2 — backend, frontend | | ● | | ● | none | |
| **grist** | 1 | ● | ● | ● | ● | community | |
| **ollama** | 1 | | | | | community | internal only |
| **people** | 3 — backend, frontend, celery | ● | ● | | ● | upstream `desk` 0.0.7 ⚠ | chart is stale |
| **clamav** | 1 | | | | | community | no consumer until Drive is wired to it |
| **observability** | 0 — dashboards only | | | | | *special* | |

## Cross-app dependencies

These are why `dependsOn` and the egress graph matter. Read as "row depends on column".

| | keycloak | livekit | collabora | ollama | find/opensearch | clamav |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| docs | ● | | ● | ● | ● | |
| drive | ● | | ● | | | ? |
| meet | ● | ● | | | | |
| conversations | ● | | | ● | | |
| bureaublad | ● | | | ● | | |
| grist | ● | | | ● | | |
| calendars | ● | | | | | |
| projects | ● | | | | | |
| find | ● | | | | ● | |
| element | ● | | | | | |

**ClamAV's only consumer was Nextcloud.** With Nextcloud dropped it has none.
**Decided: deferred.** It may be added later for Drive upload scanning, at which point it is a
tier-1 app plus one egress rule. Do not build it, size it, or carry its signature PVC now.

## Per-app notes that will cost you a day each if missed

### docs — the hardest app, and the right first build

Five workloads and **five routes on one hostname**:

| Path | Component | Note |
|---|---|---|
| `/` | frontend | |
| `/api` | backend | |
| `/admin` | backend | |
| `/media` | backend | large uploads — needs a body-size allowance |
| `/collaboration/ws` | yprovider | **websocket, needs a long timeout** |

Plus: a Celery worker; `docspec` on port 4000 (document conversion); Django `migrate`; a
`waffle` flag bootstrap Job that must set `flag_find_full_text_search` — the
`waffle_flag --everyone --create` CLI is unreliable, use the ORM
(`Flag.objects.update_or_create`). NOT `flag_find_hybrid_search`: hybrid/semantic search was
deleted upstream in `cb7d1e8` (2026-05-05, "remove embedding/hybrid search, keep BM25 only"),
so setting it advertises a feature the server does not have. Integrates with Find over a
50-character service token, with Collabora for editing, and optionally with Ollama.

If `platform-lib` carries Docs without an escape hatch, it carries everything.

### drive

Two Celery deployments, not one — a worker and a beat scheduler. Beat must never run more
than one replica. Three routes: `/`, `/media`, `/media-preview`.

### calendars

The awkward one. Four workloads including a **CalDAV container that is SabreDAV under Apache**
and needs a relaxed security context (`runAsUser: 33`, writable root filesystem) — the only
place in the platform where the platform default doesn't hold. Also the **only app never
migrated to Gateway API**: it still has `ingress.yaml` and no HTTPRoute. Routing for it is
net-new work, not a port.

### projects

Not Django, and it shows in every spelling: `DATABASE_URL`, `REDIS_URL`, `S3_*`, `SMTP_*`
and an `OIDC_ISSUER` it discovers everything from — five new profiles, one family
(`apps/projects/README.md`). One process serves the SPA, the API and socket.io, and most of
the UI's writes go over the socket, so `/socket.io` is a websocket route or the UI stops
saving. Upstream links avatars straight to the bucket; the fork's `S3_PROXY_PUBLIC_FILES`
streams them through the server instead, so the bucket stays private. No chart upstream —
ours is Docs' cut down to one workload.

### element / synapse — stays, on ESS Community

**Correction to an earlier draft**, which claimed ESS Community was "licensed for
non-commercial deployments up to 100 users" and recommended dropping Matrix. Both halves were
wrong.

**The licence is AGPL-3.0**, which places no restriction on commercial use or on the number
of users. The "up to 100 users, non-commercial" line is Element's README **positioning** for
the Community edition, describing who they built it for and where ESS Pro takes over — not a
licence term. Running ESS Community commercially for 5,000 users is permitted.

Element publishes `element-hq/ess-helm` (the `matrix-stack` chart): Synapse with worker
support, Matrix Authentication Service, Element Web and Admin, HAProxy, PostgreSQL and Matrix
RTC. So Element is a **consume-upstream app like the rest**, not the large chart we would
otherwise have owned.

It is, however, the app that fits the surround least well: it bundles its **own PostgreSQL**
(disable it, point Synapse and MAS at the shared CNPG cluster, or accept a second Postgres to
back up), its **own ingress and `.well-known` handling**, and its **own HAProxy** in front of
Synapse's workers — so its component/service map is larger and less stable than the others'.
Budget M8 accordingly: it is the one place where "just consume upstream" may cost more than
writing the surround did.

What the positioning does tell us, and what to plan around:

| Concern | Reality |
|---|---|
| **Commercial use** | Permitted — AGPL-3.0 |
| **Above 100 users** | Permitted. Whether the Community chart's defaults *scale* there is a technical question to answer at M8, not a legal one. Synapse worker support is in the chart |
| **Support** | None. ESS Pro is the paid path, and the sane upgrade for a large customer |
| **AGPL obligations** | Mild if we deploy it unmodified. If we modify Synapse or ESS and offer it over a network, source disclosure applies. Note Synapse itself has been AGPL-3.0 since 2023, so this holds for any Synapse deployment |
| **EUPL-1.2 compatibility** | Fine. EUPL lists AGPL-3.0 as compatible, and we are composing containers, not linking code |

**Matrix stays in scope.** Element/Synapse is the only team chat in the suite — Conversations
is an LLM assistant, not an instant messenger (see below), so dropping Matrix would leave the
platform with no messaging at all.

Two things still true: `matrixDomain` can only be set once and is permanent, so settle it
before the first install; and Matrix 2.0 moved authentication to MAS, so the old repo's
direct-OIDC Synapse configuration is not a usable reference — the Keycloak realm work
(`history/design/07-identity-and-secrets.md`) needs an MAS-shaped client rather than a Synapse-shaped one.

### conversations — an LLM assistant, not team chat

Worth stating plainly because the name misleads and an earlier draft of this document got it
wrong: **Conversations is an AI chatbot.** It needs an LLM backend — Ollama locally, or an
external OpenAI-compatible endpoint — and it does not provide human-to-human messaging.

Consequences:

- It does **not** substitute for Matrix. The suite's chat story is Element; the suite's AI
  story is Conversations.
- It is optional in a way Element is not. With no LLM configured it has nothing to do, so a
  deployment without AI simply leaves it disabled.
- It is one of four AI consumers alongside Docs, Bureaublad and Grist, all of which must
  degrade cleanly when no LLM endpoint is configured.

### people — wanted, chart is stale

La Suite directory and team management: teams, organisations, and a user directory the other
apps can consume. Three workloads (backend, frontend, celery), Postgres and cache.

**Usable, with caveats.** The `desk` chart is v0.0.7, published **April 2025** — 17 months
old while Docs and Drive ship monthly. Two known defects:

- The `createsuperuser` Job templates its `command` as a YAML string instead of an array, so
  Kubernetes rejects it. Disable it and create the superuser from our own Job.
- The waffle menu is unconditionally rendered against `lasuite.numerique.gouv.fr` with no
  flag to disable it. Needs an upstream PR (see below).

Neither is a reason to skip the app. Both are `known-limitations.md` entries. If the chart
stays unmaintained, People becomes our third `mb-*` chart — the application is wanted, the
chart is replaceable.

### livekit — the Gateway API exception

Built as planned, with two narrowings. Signaling goes through the Gateway like any app
(`wss://livekit.<domain>`); media goes through the Gateway too, as L4 listeners (adr/0113)
with ONE multiplexed UDP port rather than a range, plus ICE/TCP and TURN/UDP. TURN over
TLS is not offered. Config lives in a Secret, not the chart's ConfigMap, and the chart's
hostPorts are stripped for PSA baseline. `apps/livekit/README.md`.

### collabora

**Must not be scaled** — multiple replicas break collaborative editing and copy/paste. PDB
disabled, replicas pinned to 1, and a relaxed security context. A good test that "PDB only
when replicas > 1" behaves.

### find

Cross-app search: one OpenSearch, indices for several apps. Backend plus a Celery worker.
Needs an index-creation bootstrap Job, and re-indexing after any OpenSearch outage or fresh
deploy must be a Job, not a runbook line.

### grist

Single workload but three datastores (PG, cache, S3). The best tier-1 smoke test for the
datastore contract.

### bureaublad

The portal. Cache but **no database**. Needs the widest OIDC scopes because it aggregates
links and status from the others.

### ollama

Optional. GPU node selector and tolerations when present; large model PVC. Consumed by
docs, conversations, bureaublad and grist for AI features — all of which must degrade
cleanly when it is disabled, since most installs will point at an external LLM endpoint
instead.

### observability

Not an app. Ships Grafana dashboards as `GrafanaDashboard` CRs. **47,885 lines of vendored
dashboard JSON — do not port it.** Use `grafanaCom: {id: …}` or `url:` references and keep
only genuinely custom dashboards in git.

## Upstream gotchas

Verified against real deployments in `lasuite-platform` (`adr/0012`). Each one costs a day if
you meet it unprepared.

### The waffle menu points at the French government

The "gaufre" app-switcher is hardcoded to `lasuite.numerique.gouv.fr` in several apps. For a
Dutch deployment this is a **product problem, not a config problem**:

| App | State |
|---|---|
| **Docs** | Configurable since v4.5.0 via `backend.themeCustomization` — usable |
| **Drive** | Fetches services from `lasuite.numerique.gouv.fr/api/services`; URLs hardcoded per theme. Currently only disableable via `FRONTEND_HIDE_GAUFRE` |
| **People** | Unconditionally rendered, script hardcoded, no flag to disable. Needs an upstream PR |
| **Conversations** | Hardcoded widget from `static.suite.anct.gouv.fr`. Needs an upstream PR |

Bureaublad is our portal, so a second app-switcher pointing at French government services is
worse than merely cosmetic. **Budget upstream PRs for Drive, People and Conversations**, and
note the Docs `themeCustomization` JSON is cached in Redis for 24h — changes do not appear
until the cache expires or the key is deleted.

### Find's indexation needs an externally-resolvable URL

**Corrected 2026-09-06 — right conclusion, wrong reason.** Find's `Production` class does
set `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` (`find/settings.py:638`)
alongside `SECURE_SSL_REDIRECT = True`, so the setting is not the unoverridable part. The
actual problem is that a **direct pod-to-pod call carries no `X-Forwarded-Proto`**: Django
301s, and `requests` downgrades a 301'd POST to a GET, so indexing silently does nothing.

Same outcome — **Docs and Drive must use the external `https://find.<domain>` address**, not
the internal service URL — but the reason matters if anyone later tries to "fix" it with a
settings override. There is nothing to override.

Consequence: works in production with real DNS; fails in local/dev clusters that fake DNS
via `/etc/hosts`. Plan the dev story around this.

### Find's migrate Job breaks every upgrade

The chart names it `find-backend-migrate-{chartVersion}`, and the chart version rarely moves.
Kubernetes Job `spec.template` is immutable, so any change to env, image or command fails
with `field is immutable` until the Job is deleted by hand. It also has
`ttlSecondsAfterFinished: 30`, which makes `--wait-for-jobs` race against garbage collection.

This is exactly the failure `platform-lib`'s job contract avoids by using Helm hooks with
`hook-delete-policy: before-hook-creation` (`history/design/04-platform-charts.md`). **Confirmed and applied
at M6**: the chart threads `backend.migrateJobAnnotations` straight through, so the fix is
values-only — see `config/apps/find/release.yaml`.

### Keycloak needs split internal/external URLs

Pods cannot resolve the browser-facing hostname the same way a browser does. OIDC config
must use **external URLs for browser redirects** (authorize, logout) and **internal service
URLs for backend calls** (token, JWKS, introspection). Keycloak needs
`KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` to accept requests on internal URLs while
`KC_HOSTNAME` is external. Fold this into the `platform.oidc` helper
(`history/design/07-identity-and-secrets.md`) rather than rediscovering it per app.

### Other verified traps

- **Redis/Valkey `FLUSHDB` disabled** breaks Django's `cache.clear()` with
  `ConnectionInterrupted`. Bitnami disables it by default; decide deliberately for Valkey.
- **Kubernetes 1.34 rejects duplicate env var names** in a pod spec. Bit both Keycloak
  (`KC_HTTP_ENABLED` set twice) and People (celery deployments inherit `backend.envVars`).
  The library must not emit a variable twice — worth a golden test.
- **Meet's chart version does not track its app version** (chart 0.0.x, app v1.x), and La
  Suite charts default `image.tag` to `latest`. Pin image tags explicitly, separate from
  chart versions.
- **Meet's realtime agents now require Deepgram**, an external paid API. Keep
  `agentSubtitles` and `agentMetadata` at zero replicas; the self-hostable path is WhisperX
  and needs a GPU.
- **ARM64 multi-arch manifests are broken** for most `lasuite/*` images since GitHub runners
  moved to Docker Engine 29. Native arm64 build PRs are open across the La Suite repos. If
  anyone develops on Apple Silicon, check this before debugging phantom pull failures.

## Apps we do not have

**People** (`suitenumerique/people`, chart `desk` v0.0.7) — directory and team management.
Not in mijn-bureau-infra. It overlaps Keycloak for authentication but adds team/organisation
structure the other apps can consume. Early-stage: the v0.0.7 chart has a broken
`createsuperuser` job and an undisableable waffle. **Worth evaluating after M6**, not before.

Also charted upstream but out of scope for now: Projects (no chart), Calc (prototype),
Messages (no deployment artifacts).

## Cross-app integration that does not exist yet

**Docs ↔ Drive is blocked upstream.** Drive ships a complete OIDC Resource Server
(`/external_api/v1.0/*`) so another app can store files in it. Docs has token storage but no
client code to call it — no `DRIVE_API` setting, no views. So "open a Docs document from
Drive" is not currently possible from configuration alone.

Worth tracking: it is the integration that would make the suite feel like one product, and
when Docs implements the client it becomes a values change, not a project. The Find service
token already proves the same OIDC Resource Server pattern works here
(`history/design/07-identity-and-secrets.md`).

## Deletions that come free

| Delete | Lines | Why |
|---|---:|---|
| Nextcloud + OpenProject | 16,834 | dropped from scope |
| Per-app static-nginx releases (5) | ~5,000 | serving a theme CSS file; bake into the frontend image |
| Per-app Bitnami values copies | 46,858 | replaced by the datastore contract |
| Vendored Grafana JSON | 47,885 | reference upstream dashboards by id |
| Ingress templates (24) | 1,329 | Gateway API only |
| ClamAV *(deferred)* | 1,333 | no consumer until Drive is wired to it |

## Sizing

~29 workloads before M8 (~34 with Element) plus one shared Postgres (3 pods), two Valkey
instances, one OpenSearch, a Gateway, and the operator set. A single-tenant install is a small cluster — which is the point, and worth
protecting: every per-app datastore instance you keep multiplies that count by fourteen.
