# 09 — What to harvest from `mijn-bureau-infra`

The old repo's value is in its knowledge, not its structure. This is the extraction list,
with exact paths, ordered by value per line.

**Licence:** `mijn-bureau-infra` is **EUPL-1.2**, which is copyleft. Lifting these files means
the new repository stays EUPL-1.2 and retains attribution. Fine in context, but decide it
deliberately — see `adr/0010`.

---

## Tier A — copy nearly verbatim

### 1. The Keycloak realm and its clients

`helmfile/apps/keycloak/keycloak.yaml.gotmpl` — **820 lines**

Nine surviving clients with working mappers, scopes, redirect URIs and `realm_client`
flags — ten once People's is added (`07-identity-and-secrets.md`).
This is the highest value per line in the entire repository and the thing most expensive to
rediscover. Extract the realm JSON, drop the Nextcloud and OpenProject clients, replace the
`derivePassword` secrets with ESO references (`07-identity-and-secrets.md`).

### 2. The OIDC contract

`helmfile/environments/default/authentication.yaml.gotmpl` — 56 lines
plus the `OIDC_*` blocks in each app's `values.yaml.gotmpl` (e.g. `apps/docs/values.yaml.gotmpl:202-232`)

The claim mapping and the 22-variable env block become one library helper. Transcribe the
variable list exactly; several of these are non-obvious (`OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION`,
`OIDC_STORE_REFRESH_TOKEN_KEY`, `OIDC_USERINFO_SHORTNAME_FIELD`).

### 3. The network egress graph

`networkPolicy.extraEgress` blocks in every `helmfile/apps/*/values.yaml.gotmpl`

This is the real service dependency graph of the platform, already debugged. It maps almost
1:1 onto the `egress:` list in `04-platform-charts.md`. Do not re-derive it by watching things
break.

### 4. Security context defaults and their exceptions

`helmfile/environments/default/security.yaml.gotmpl` — 66 lines

The platform default plus the two real exceptions (Collabora; Calendars' CalDAV at
`runAsUser: 33` with a writable root filesystem). Exceptions of this kind are only ever
discovered the hard way.

### 5. Policy rules

`policy/containers.rego` (217), `policy/image.rego` (98), `policy/labels.rego` (196),
`policy/namespace.rego` (8), plus `tests/*/*.rego` (24 files)

Port to Kyverno, or keep Conftest for render-time checks and use Kyverno for admission. The
*rules* are the asset; the engine is a detail.

---

## Tier B — mine for facts, rewrite the form

### 6. Per-app application wiring

`helmfile/apps/<app>/values.yaml.gotmpl` — 5,394 lines across the kept apps

| Path | Lines | What's in it |
|---|---:|---|
| `apps/docs/values.yaml.gotmpl` | 687 | 5-component wiring, waffle-flag Job, Find/Collabora/Ollama integration |
| `apps/grist/values.yaml.gotmpl` | 366 | 3 datastores, AI wiring |
| `apps/calendars/values.yaml.gotmpl` | 283 | CalDAV, worker |
| `apps/drive/values.yaml.gotmpl` | 242 | Celery + beat, media routes |
| `apps/meet/values.yaml.gotmpl` | 205 | LiveKit integration |
| `apps/bureaublad/values.yaml.gotmpl` | 174 | portal aggregation |
| `apps/livekit/values.yaml.gotmpl` | 112 | RTC port range, TURN domain + TLS |
| `apps/find/values.yaml.gotmpl` | 106 | OpenSearch wiring |
| `apps/ollama/values.yaml.gotmpl` | 98 | GPU/model config |
| `apps/clamav/values.yaml.gotmpl` | 52 | signature volume |
| `apps/collabora/values-collabora.yaml.gotmpl` | 220 | WOPI, no-scale constraint |
| `apps/conversations/values-conversations.yaml.gotmpl` | 141 | Ollama/AI wiring |

Read each one once, extract the env vars and integration facts, then write the new app file
from the contract in `05-app-contract.md`. Do not port them structurally.

### 7. The configuration inventory

`helmfile/environments/default/` — 1,570 lines across 23 files

The *shape* is wrong (it re-models Kubernetes; see `01-decision.md`). The *inventory* is
right: it is an exhaustive list of what has to be configurable. Use it as a checklist when
writing `values.schema.json`, then throw the files away. Particularly worth reading:
`global.yaml.gotmpl` (hostname map), `database.yaml.gotmpl`, `objectstore.yaml.gotmpl`,
`cluster.yaml.gotmpl` (routing modes, runtimeClassName).

### 8. Chart templates as reference

`helmfile/apps/*/charts/*/templates/` — ~37,800 lines

Read them; don't port them. They encode the real container arguments, ports, volume mounts
and probe endpoints for each upstream image. The one that still matters is **Calendars' CalDAV
container** — the only app besides Bureaublad with no upstream chart.

Note the old repo's `synapse` chart and its OIDC client are **not** a useful reference any
more: Element's ESS chart supersedes the chart, and Matrix 2.0 moved authentication to MAS,
so the direct-Synapse OIDC configuration no longer reflects how this is done.

**Correction:** an earlier draft said La Suite's charts are "thin or absent". They are not —
DINUM actively publishes charts for Docs, Drive, Meet, People, Conversations and Find
(`adr/0012`). For those five apps, the upstream chart is a better reference than
mijn-bureau-infra's, and possibly a better *implementation*. Read the upstream chart first.

### 9. Documentation

`docs/docs/` — 452 KB, including **14 ADRs**, per-component pages and per-component diagrams

The ADRs capture *why*, which is what survives a rewrite. Carry forward the ones still true
(Kubernetes as the platform, gitmoji commits, resource labels, container image sources) and
supersede the rest with the ADRs in `adr/`. Reuse the component and feature pages nearly
as-is.

### 10. Operational odds and ends

| Path | Why |
|---|---|
| `scripts/airgap_prepare.py` (201) | Air-gapped install is a real requirement for public sector; the image-mirroring logic transfers |
| `scripts/kind.sh` (240) | Local cluster bootstrap; adapt for the Flux bootstrap test |
| `.gitlint` + `scripts/gitlint_emoji.py` | Commit convention already agreed and tooled |
| `helmfile/apps/common/charts/gateway/` | Small, already Gateway-API-native, and the hostname-collection pattern is worth keeping |

---

## Do not carry forward

| Thing | Lines | Why |
|---|---:|---|
| Copied Bitnami values files | 46,858 | The reason for the rebuild |
| Bitnami `common` 2.31.1 library chart | — | Unmaintained; the idiom it imposes is the porting cost |
| Vendored Bitnami redis/postgresql/minio/nginx charts | — | Replaced by the datastore contract |
| Vendored Grafana dashboard JSON | 47,885 | Reference upstream by id |
| `derivePassword` secret derivation | — | See `07`; do not port it "just for now" |
| `environments/default/` file structure | 1,570 | Inventory yes, shape no |
| Child helmfiles and `needs:` ordering | ~800 | Replaced by Flux `dependsOn` |
| Nextcloud and OpenProject | 16,834 | Out of scope |

---

## Tier C — the second source: `lasuite-platform`

An unaffiliated individual's reference deployment of La Suite
([baptisterajaut/lasuite-platform](https://github.com/baptisterajaut/lasuite-platform)).
~5,000 lines total, consuming upstream charts. Deliberately not production-grade — but it
has been run against real upstream releases, and that shows.

**Licence caution:** the repository states no licence. Take *facts and ideas* from it, not
files. Everything below is a fact about upstream software or a pattern, not copyable code.

### 11. `docs/known-limitations.md` — the practice and the content

417 lines cataloguing real upstream breakage with links to the issues and PRs. Adopt both:

- **The practice.** A living `known-limitations.md` is the cheapest high-value document a
  platform can keep. See `10-verification.md`.
- **The content.** Much of it applies to us directly — see the gotcha list in
  `08-app-inventory.md` and `06-datastores.md`.

### 12. `docs/decisions.md` — a survey of what exists

Its inventory of the whole `suitenumerique` org is worth reading once: which apps have
charts, which are prototypes, which have no deployment artifacts at all. It is the fastest
way to know what could be added later (People, Projects, Calc) and what cannot.

### 13. `versions/*.yaml` — versions as data

Two files holding every chart version and every image-tag override, separate from all logic.
Renovate-friendly, greppable, and it makes "what are we running" a one-file answer. Our
`config/clusters/<env>/sources.yaml` should follow the same principle.

### 14. `secretOverrides` — the escape hatch on generated secrets

Their `getSecret` helper checks a per-id override map before falling back to derivation. We
generate rather than derive (`adr/0005`), but the *shape* is directly useful: it lets a
single credential be moved to a real secret store without migrating all of them at once.
Build the same indirection into `platform-deps`'s secret resolution.

### 15. `generate-compose.sh` + `dekube.yaml.template`

Transpiles the same Helmfile output into `compose.yml` + Caddyfile via
`helmfile2compose`/dekube, for installs with no Kubernetes. Not our architecture — but the
old repo also had `scripts/single-vps-deploy`, so the requirement is real for small
organisations. Worth knowing this path exists before anyone builds a second one.

## Extraction order

Harvest is not a phase; it happens inside the milestones in `11-roadmap.md`. But do items
**1, 4 and 5** first and in full — realm, security defaults, policy rules. They are
platform-level, they block everything else, and they are the three most expensive things to
rediscover.
