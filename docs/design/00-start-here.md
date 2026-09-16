# 00 — Start here

**Read this file first. It is the handoff brief: enough to begin, plus where to look for
everything else.** The design set is ~3,000 lines across 25 files; this is the 250 that get
you building. Every claim here is expanded somewhere, and the pointer is given.

---

## What you are building

A Kubernetes platform running the **MijnBureau** collaborative suite — 14 applications for
Dutch public-sector organisations, deployed by Flux from git, sized for anywhere between 5
and 5,000 users.

It replaces `mijn-bureau-infra`, a Helmfile repository of ~105,000 authored lines. The
replacement is ~4,000 lines of config plus ~1,600 of platform charts and policy. That
reduction comes from one decision: **we consume other people's Helm charts and build only
the surround.** DINUM (the French government) actively maintains charts for Docs, Drive,
Meet, Conversations, Find and People; vendor or community charts exist for everything else
except Calendars and Bureaublad, which are the only two we template ourselves.

Read `01-decision.md` for why, `adr/0012` for the discovery that shaped it.

## Two repositories

| Repo | Contents | Released as |
|---|---|---|
| **`platform`** | 4 Helm charts, 2 app charts, Kyverno policy, tests, CI | OCI artifacts, cosign-signed |
| **`config`** | Flux clusters, infra operators, shared datastores, 14 app files | reconciled by Flux |

Both **EUPL-1.2** (`adr/0010`), because we lift material from `mijn-bureau-infra` which is
EUPL-1.2 and copyleft. Layout in `03-repo-layout.md`; do not invent a different one.

The four charts in `platform` (`04-platform-charts.md`):

- **`platform-app`** — the surround: HTTPRoutes, NetworkPolicy, PDB, ServiceMonitor,
  PrometheusRule, around a workload someone else's chart created. ~400 lines.
- **`platform-deps`** — everything an app needs *before* it starts: Postgres, cache, object
  store, search, plus the OIDC and service-token Secrets. ~400 lines.
- **`platform-infra`** — cluster singletons: the shared Gateway, PriorityClasses,
  ClusterIssuer. ~150 lines.
- **`platform-lib`** — a small library chart shared by the above and by our two app charts.
  ~250 lines.

Plus `mb-calendars` and `mb-bureaublad`, ~40 lines each.

## The six principles

These are the decision rules. When something is ambiguous, resolve it with these, in order.
Full text in `02-architecture.md`.

1. **P1 — Publish the base; don't copy it.** Versioned OCI artifact, never vendored files.
2. **P2 — Never re-model a Kubernetes API.** Probes, resources, volumes, tolerations,
   securityContext pass through verbatim with `toYaml`. No `probes.liveness.httpGet.path`.
3. **P3 — Model only what Kubernetes lacks.** `host`, `oidc.client`, `egress`. The chart's
   own API should fit on one screen.
4. **P4 — Contracts, not implementations.** The app knows "a Secret exists at this name with
   these keys". It never learns what CloudNativePG or Garage is.
5. **P5 — Exceptions have a home.** Used once, escape hatch. Used three times, a feature.
6. **P6 — Don't build for requirements we don't have.** Every operator is an upgrade cycle
   owned forever.

## The shape of an application

One file, three HelmReleases, in this order. This is the single most important artifact in
the design set — the worked example for Docs, the hardest app, is in `05-app-contract.md`
and is ~85 lines.

```
config/apps/docs.yaml
  1. docs-deps      platform-deps   → datastores + OIDC Secret + service tokens
  2. docs           upstream chart  → the workload, ingress disabled, image pinned
  3. docs-platform  platform-app    → routes, netpol, PDB, metrics; selects into (2)
```

A simple app is 25–40 lines. **The marginal cost of a new application is one file** — that
number is the whole justification for the rebuild, so measure it and defend it.

---

## Fourteen defaults that are wrong here

Each of these is a correction someone already had to make. Violating one is not a style
disagreement; it is a bug the design set already names.

1. **Never `derivePassword`.** Not even as an interim. Secrets are generated once in-cluster
   by ESO or the owning operator. The only things in git are SOPS-encrypted bootstrap roots.
   `adr/0005`, `07-identity-and-secrets.md`.
2. **Never put edge OIDC in front of an app.** All ten OIDC apps authenticate in-app via
   mozilla-django-oidc with their own sessions. Fronting them double-authenticates.
   `adr/0006`.
3. **OIDC endpoints split internal/external.** Browser redirects use the external hostname;
   backend token/JWKS calls use the internal service URL. Keycloak needs
   `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`. Getting this wrong looks like a credentials bug.
4. **Secrets come from release 1, never from the surround.** The surround runs *after* the
   app that must read them at startup.
5. **The OIDC block is a Secret consumed with `envFrom`**, not values spliced into an
   upstream chart. A library helper cannot reach inside DINUM's templates.
6. **`components` carries a Service *and* a selector.** An HTTPRoute backend is a Service;
   NetworkPolicy, PDB and ServiceMonitor take label selectors. They are not interchangeable
   and upstream service names are not derivable from component labels.
7. **Kyverno must not mutate `runAsUser` or `readOnlyRootFilesystem` cluster-wide.** Those
   defaults came from Bitnami images in charts we templated. Applied to Keycloak, CNPG,
   Garage, OpenSearch, Envoy and DINUM's images, they break a fresh bootstrap. Mutate only
   caps / privilege-escalation / seccomp; validate the rest. `adr/0013`.
8. **Always pin `image.tag` separately from the chart version.** Every La Suite chart
   declares `appVersion: latest`. Meet's chart version does not track its app version at all.
9. **Disable the upstream chart's ingress, PDB, ServiceMonitor, HPA and NetworkPolicy.**
   Two PDBs over the same pods is a node drain that never completes.
10. **`install.disableWaitForJobs` and `upgrade.disableWaitForJobs` on every release** — and
    accept that Flux then reports Ready before migrations finish. Those are the real Flux
    field names; `waitForJobs` is not a key.
11. **`upgrade.remediation.retries: 0` wherever there is a migration Job.** A Helm rollback
    reverts code and not schema.
12. **Two shared Valkey instances, not one.** Eviction policy is per instance, not per
    logical DB, and an evicting Celery broker silently drops tasks. `06-datastores.md`.
13. **Size profiles are one file per profile, not one patch.** The upstream charts do not
    share a values schema, and a strategic-merge patch on a path a chart lacks is a silent
    no-op. `05-app-contract.md`.
14. **`${TENANT}` reaches only what the Helm release name reaches.** It cannot rename
    resources generated inside an upstream chart. `adr/0008`.

## Two things to verify rather than trust

**Version numbers in these documents were checked in September 2026 and will have moved.**
Chart versions, the CNPG minimum for declarative `Database` extensions, Envoy Gateway's
`ClientTrafficPolicy` field names, garage-operator's Garage version floor — re-check each
before pinning. The reasoning in these files survives; the numbers do not.

**Do not invent values keys.** Every upstream chart has a `values.yaml` and usually a schema.
Read it. A key that does not exist fails silently, and that is the single most common way
this architecture breaks.

---

## Start with M1

`11-roadmap.md` has all nine milestones. M1 is:

- Both repos created, EUPL-1.2, with the CI from `10-verification.md`
- `platform-infra`: shared Gateway, PriorityClasses, ClusterIssuer
- `config/clusters/dev`: Flux bootstrap, four Kustomizations (`10-crds` → `20-infra` →
  `30-platform` → `40-apps`), `vars.yaml` with `${BASE_DOMAIN}`, `${STORAGE_CLASS}`,
  `${TENANT}`
- `config/infra`: cert-manager, Envoy Gateway, ESO, CNPG, garage-operator, Kyverno (audit),
  kube-prometheus-stack — garage-operator's webhooks need cert-manager reconciled first
- The certificate strategy: wildcard or per-host, DNS-01 either way, because LiveKit's
  `turn-livekit` certificate sits on a UDP LoadBalancer outside the Gateway
- Pod Security Admission labels on the namespace template
- OCI release pipeline: tag → `helm push` → cosign sign

**Done when:** `flux bootstrap` on a kind cluster brings up the operators and the Gateway
gets a certificate, from nothing, in CI.

Then M2 (identity and secrets) before any application, because every app added under a
temporary secret scheme is an app to migrate later.

**Build Docs before the easy apps** (M4). Proving the surround against three simple apps and
then meeting Docs is how `platform-app` acquires a second, incompatible shape.

---

## Which file answers which question

| Question | File |
|---|---|
| Why rebuild rather than refactor? | `01-decision.md` |
| What are the principles and the stack? | `02-architecture.md` |
| Where does this file go? | `03-repo-layout.md` |
| What do our four charts do? | `04-platform-charts.md` |
| What does an app file look like? Sizing 5→5,000? | `05-app-contract.md` |
| Postgres / cache / S3 / search contracts | `06-datastores.md` |
| Keycloak, OIDC, secrets | `07-identity-and-secrets.md` |
| **What each of the 14 apps actually is, and its traps** | **`08-app-inventory.md`** |
| What to lift from the old repo, with exact paths | `09-harvest.md` |
| What catches which bug, and when | `10-verification.md` |
| Build order and exit criteria | `11-roadmap.md` |
| Why a decision was made | `adr/` |

`08-app-inventory.md` is the highest-value file in the set. Read it before writing any app
file — it is where the day-costing traps live: Find's `SECURE_SSL_REDIRECT`, the waffle menu
pointing at the French government, Collabora's no-scale constraint, Calendars' CalDAV
security context, People's broken `createsuperuser` Job.

## What to harvest, and first

From `mijn-bureau-infra` (`09-harvest.md`), do these three first and in full — they are
platform-level, they block everything else, and they are the most expensive to rediscover:

1. **The Keycloak realm** — `helmfile/apps/keycloak/keycloak.yaml.gotmpl`, 820 lines, nine
   surviving clients with working mappers, scopes and redirect URIs; People's is the tenth
   and is net-new.
2. **Security-context defaults and their two real exceptions** —
   `helmfile/environments/default/security.yaml.gotmpl`.
3. **The policy rules** — `policy/*.rego`, ported to Kyverno. The rules are the asset; the
   engine is a detail.

Also: the network egress graph lives in the `networkPolicy.extraEgress` blocks of every
`helmfile/apps/*/values.yaml.gotmpl`. It is the real service dependency graph, already
debugged. Do not re-derive it by watching things break.

## The commit convention

gitmoji, with scopes from the old repo: app folder names, plus `settings`, `deps`, `docs`,
`tests`, `policies`, `ci`, `other`. Example: `✨ (grist) add resource limits`. The gitlint
config and `scripts/gitlint_emoji.py` are worth carrying over as-is.
