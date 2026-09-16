# 01 — Decision: rebuild, harvest hard

**Decision:** start a fresh pair of repositories on the architecture in `02-architecture.md`.
Lift the integration knowledge, the Keycloak realm, the network-egress graph and the policy
rules out of `mijn-bureau-infra`. Do not carry its structure.

This is not a judgement on the work. It is careful work. But the thing that needs fixing
*is* its architecture, and the thing worth keeping transfers cleanly into a new repo anyway.

## What the old repo measures

Authored configuration in `helmfile/`, excluding vendored upstream charts:

| Category | LOC |
|---|---:|
| Per-app copies of Bitnami `values.yaml` (36 files) | **56,996** |
| Authored Helm chart templates (15 kept apps) | 37,788 |
| Per-app integration wiring (`values.yaml.gotmpl`) | 6,381 (5,394 in the apps we keep) |
| `environments/default/` config tree (23 files) | 1,570 |
| Child helmfiles (18) | ~800 |
| Rego policy + tests | ~1,000 |
| *Vendored Grafana dashboard JSON* | *47,885* |

Of the 56,996 lines of copied Bitnami values: **1,695 lines contain a template expression**
(3%) and **38,654 lines are comments** (68%). `apps/docs/values-redis.yaml.gotmpl` and
`apps/drive/values-redis.yaml.gotmpl` are 2,326 lines each and differ by **78 lines**.

The single clearest example: `apps/docs/values-static-nginx.yaml.gotmpl` is 978 lines of
Bitnami nginx values whose operative content is `location / { root /static; }` — it serves a
theme CSS file. Five applications have one.

## Four structural reasons, not cleanup items

**1. Bitnami is the substrate, not a dependency.**
All 23 authored charts declare `common: 2.31.1` — the Bitnami library chart — and are
written in its dialect: `common.tplvalues.render`, `common.affinities.pods`,
`common.compatibility.renderSecurityContext`, `resourcesPreset`. Removing Bitnami is not
"swap Redis for Valkey". It is rewriting every template's helper calls, or vendoring a dead
library chart forever. The leading edge of this has already been hit — `common.warnings.rollingTag`
had to be stripped from vendored charts by hand.

**2. Helmfile has no library-chart layer, so the duplication is load-bearing.**
Helm values files cannot be composed or inherited. That is *why* there are ten forks of the
Bitnami Redis values. No refactor fixes this while staying on helmfile-with-values-per-release.

**3. The config tree re-models Kubernetes.**
`pvc.docs.redis.storageClass`, `resource.docs.backend`, `autoscaling.horizontal.docs.backend`,
`pdb.docs.backend` — 23 top-level value files, each keyed app-then-component. Every new app
touches all of them. Every new Kubernetes field means adding a bespoke value for it.

**4. There is no real GitOps and no path to one.**
`docs/gitops.md` documents an ArgoCD `ConfigManagementPlugin` that shells out to
`helmfile template`: no per-release drift detection, no health-gated ordering. Flux does not
support helmfile at all. Ordering today is string-concatenated `needs:`
(`{{ if .Values.application.docs.namespace }}{{ . }}/{{ end }}docs-cluster`, repeated per
release per app). Any move to GitOps replaces this layer wholesale.

Supporting facts: the upstream is effectively stalled (last non-dependabot commit 2026-07-09),
so continuing means maintaining a fork that cannot merge back; and multi-tenancy is genuinely
absent — the optional per-app `namespace` is app isolation, one realm, one domain, one
`derivePassword` root.

## What the rebuild actually saves

| Saving | LOC | Earned by |
|---|---:|---|
| Drop Nextcloud + OpenProject | 16,834 | already decided |
| Delete copied Bitnami values | 46,858 → ~300 | dropping Bitnami — any architecture |
| **All authored app charts** | **37,788 → ~1,200** | **consuming upstream charts** (`adr/0012`) |
| `environments/default/` tree | 1,570 → ~400 | dropping the re-modelled schema |
| Per-app integration wiring | 5,394 → ~900 | upstream charts absorb most of it |

**~105,000 → ~4,000**, plus ~1,200 lines of platform charts and ~400 of Kyverno policy.

Split honestly: **~60% is free** — drop two apps, drop Bitnami; you get that under any
architecture, including cleanup-in-place. **The rest comes from not writing charts at all.**
DINUM maintains charts for Docs, Drive, Meet, Conversations, Find and People; vendor or
community charts exist for Keycloak, LiveKit, OpenSearch, Collabora, Ollama and Grist. Only
Calendars and Bureaublad need one from us.

The duplication the first draft planned to collapse — 21 PDB templates, 23 HPAs, 57 Services,
35 NetworkPolicies, all near-identical — was real. It just turned out that upstream had
already absorbed it, and the right move was to stop owning that layer rather than to
de-duplicate our copy of it.

## The number that decides it

The marginal cost of application #16:

- **Today:** 6,000–9,000 lines — a child helmfile, 3–4 copied Bitnami values files, a chart,
  plus edits across ~15 files in `environments/default/`.
- **After:** 25–70 lines in one file — three HelmReleases: datastores, the upstream chart,
  our surround.

For a platform meant to be run by a few organisations over years, that ratio is the decision.

## What we are explicitly *not* claiming

- That the old repo is low quality. Its chart templates are careful and its ADRs are good.
- That the rebuild is quick. `08-app-inventory.md` is honest about which apps are hard, and
  `adr/0012` about what we now depend on other people for.
- That a cleanup-in-place would fail. It would recover ~60% of the lines. It would not fix
  reasons 1–4, and the marginal-cost-per-app number would barely move.

See `adr/0001-fresh-repository.md`.
