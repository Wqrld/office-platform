# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## What this is

A GitOps distribution of La Suite numérique (Docs, Drive, Calendars, Meet, Messages, Projects,
plus Find, Collabora, LiveKit) for Kubernetes. No application code lives here: it is Flux
Kustomizations, HelmReleases of upstream charts, four charts of our own, and Python/shell
checks that render it all offline. An organisation installs it from one values file
(`examples/cluster.yaml`); nothing per cluster lives in this repo.

## Checks (no cluster needed)

Every job in `.github/workflows/pr.yaml` runs one of these, so the check that fails in CI is
the check you can run here. `tests/toolchain.sh <tool…>` installs the pinned helm, flux,
kubeconform, conftest, dyff and gitleaks (pins are read from the workflow's `env:`); the
scripts need Python 3 + PyYAML.

| Command | Question it answers |
|---|---|
| `./tests/render.py <case>` (`--list` for names) | what does this case render to? (every chart check renders through it) |
| `./tests/schema.py` | do the schemas — and the control plane's refusals — still reject a bad values file? |
| `./tests/golden.py [--update]` | did this template change alter the output? `--update`, then read the diff |
| `./tests/build.py [dir]` | does every layer of every cluster build, with no `${VAR}` left unresolved, do the app table, `apps/`, the example and the updatecli pins agree, and is monitoring still a leaf? (CI: `built`) |
| `./tests/kubeconform.sh [dir…]` | is what the charts render and what Flux would apply valid for the API server? (CI: `tests/golden built`) |
| `./tests/render-diff.sh [base]` | what does this change do to what the clusters actually apply? (never fails; CI posts it to the job summary) |
| `./tests/binding.py [app…]` | does our surround still attach to what the upstream charts create? (the only check that notices an upstream rename) |
| `./tests/profiles.py [size…]` | do the three sizes still say what they claim — every replica count with its budget, every sized release with every size, no release file overriding one? |
| `./tests/check-secrets.py [app…]` | do the `postRenderers` envFrom patches still hit exactly the workloads they should? |
| `./tests/startup.py [app…]` | will every pod start — can each non-root container run as its image's user, and does every Secret and ConfigMap a release needs come from something it does not wait behind? |
| `pytest tests/unit` | do the helpers the checks share still behave, and do the charts agree with themselves (shared helpers identical, values.yaml = schema, every env profile used)? |
| `./tests/refs.py` | does every `apps/…`, `charts/…`, `docs/…` path a comment or README names still exist? |
| `ruff check .` and `shellcheck install.sh release.sh tests/*.sh …` | is the Python and shell lint-clean? (CI: `lint`) |
| `conftest verify --policy policy/charts && conftest verify --policy policy/config` | do the static rules still fire, both directions? |
| `conftest test --policy policy/charts --parser yaml --all-namespaces tests/golden/` | does the rendered output satisfy them? |
| `conftest test --policy policy/config --parser yaml --all-namespaces apps/ platform/ infra/ cluster/ monitoring/ tests/golden/` | are the pins and remediation settings still as decided? |

CI also runs `helm lint --strict` on each chart (`platform-app` needs
`--values tests/cases/minimal-app.yaml`, `control-plane` needs
`--values tests/cases/cluster-default.yaml`), gitleaks over the tree and history, and
gitlint over the commits.

`binding.py`, `profiles.py`, `check-secrets.py` and `startup.py` fetch the pinned upstream
charts into `.charts/` (`startup.py` also each image's config, from its registry), so they
need network; everything else is offline. All checks render through `tests/render.py` — the
control plane with `helm template`, each layer with `flux build`, HelmRelease values merged
from `valuesFrom` and `postRenderers` applied as helm-controller does (`render.releases`) —
so what a check sees is what the cluster applies, sizes and switcher files included.
`tests/cases/index.yaml` is the list of cases every chart check iterates; a case added there
is picked up by all of them. The `cluster-*` cases double as the clusters `build.py`,
kubeconform and `dns.py` run against. Every script takes `--help`, and every check ends with
its problems and one `OK —` or `FAIL —` line (`render.report`).

Any change to a template or to `tests/cases/` changes a golden: run `./tests/golden.py
--update` and commit the reviewed diff with the change.

Nothing here needs a cluster; `./preflight.py cluster.yaml` checks a live one has what a
`cluster.yaml` assumes. An install from scratch is not yet run by CI.

Other tools: `./dns.py [case|cluster.yaml] [--check] [--zone]` (DNS records a cluster
needs), `./measure.py render --size <size>` (resource totals), `updatecli diff|apply
--config updatecli/updatecli.d --values updatecli/values.yaml` from repo root (upstream pin
bumps).

## Architecture

The Flux-reconciled configuration, the charts that render it, and the checks that keep both
honest. Released as one git tag that carries the config and the four charts (adr/0114), and
installed by an organisation from one file of its own (`examples/cluster.yaml`). Design and
decisions: `docs/adr/`, the original design set in `docs/history/`.

```
charts/
  control-plane/   the chart an organisation installs: renders the Flux control plane —
                   sources, cluster vars, one Kustomization per layer and per ENABLED app —
                   from ~10 typed, schema-checked values (its values.yaml)
  platform-deps/   everything an app needs BEFORE it starts: datastores + secrets
  platform-app/    the surround: HTTPRoutes, NetworkPolicy, PDB
  platform-tenants/ what the platform provisions per app: database, cache users, OIDC secret, grant
examples/          cluster.yaml — the one file an organisation keeps, in a source of its own
cluster/           what the platform installs when the cluster lacks it: Envoy Gateway, MetalLB,
                   the Prometheus stack (adr/0112, adr/0119)
monitoring/        rules, probes and alert routing — a leaf nothing depends on (adr/0119)
infra/             operators (CNPG, ESO, the Garage operator; cert-manager when asked)
platform/          shared stateful layer — gateway, postgres, valkey, search, keycloak, and
                   the datastores of every app whether enabled or not; objectstore/ is its
                   own layer so `objectStore.mode: external` can leave it out;
                   overlays/size-* size it as kustomize components
apps/              one directory per application, each its own Flux Kustomization, with
                   its three sizes in apps/<app>/sizes/ (apps/README.md, Sizing)
policy/            conftest rules — charts/ over what the charts render, config/ over the sources
tests/             every check above, and the cases and goldens they share
```

**Control plane.** `charts/control-plane` is the only thing a cluster reads directly. It
renders the Flux sources, a `cluster-vars` ConfigMap (substituted into every layer via
`postBuild`), and one Kustomization per layer and per enabled app. Reconcile order:
`cluster-*` → `infra` → `platform` → `objectstore` → `app-<name>`, with the dependencies
between applications as `dependsOn` edges from `charts/control-plane/apps.yaml`.
`cluster-monitoring` → `monitoring` is a leaf beside them: nothing waits for it, and
`tests/build.py` fails if anything starts to (adr/0119). Cluster
singletons (the Gateway, PriorityClasses, ClusterIssuers) are plain manifests in
`platform/`, not a chart (adr/0101).

**`charts/control-plane/apps.yaml` is the application table** — defaults, hosts (→ the
certificate's SAN list), `requires`, switcher entries, and what the platform provisions per
app (postgres db, Valkey ACL users, OIDC client shape, OpenSearch index patterns, bucket).
Its header is the field reference. It is passed (all apps, enabled or not) to
`platform-tenants` as `TENANTS_JSON`.

**Nothing per cluster lives here.** A cluster is a `cluster.yaml` in the organisation's own
source; the `cluster-*` cases in `tests/cases/` are the values files the checks build: the
defaults, the small profile, every app at `large`, a minimal selection on external S3, and a
fresh VPS as `install.sh` writes it.

**Each app is three releases, in order** (see `apps/README.md`):
- `deps.yaml` → `<app>-deps` (`charts/platform-deps`): Secrets/OIDC/bucket/tokens the app
  needs before it starts, shaped per app via named env profiles (adr/0106).
- `release.yaml` → the upstream chart (La Suite charts come from pinned git refs, adr/0104;
  pins in `charts/control-plane/templates/sources.yaml`), Secrets wired in via
  `postRenderers` envFrom patches.
- `surround.yaml` → `<app>-platform` (`charts/platform-app`): HTTPRoutes, traffic policy,
  NetworkPolicy, PDB, media proxy, static files.

**Sizing:** `small|medium|large`, chosen by `size` in cluster.yaml → `SIZE` in cluster-vars.
Each app has `sizes/<size>.yaml` (upstream values shape) and `sizes/platform-large.yaml`
(PDBs), turned into a `<app>-sizes` ConfigMap consumed via `valuesFrom`. Because
`spec.values` beats `valuesFrom`, **no sizing key may live in `release.yaml` or
`surround.yaml`** (`tests/profiles.py` enforces). Lists carrying sizes are restated whole in
each size file. Some things must not vary by size (Collabora/SFU replicas, Drive celery-beat,
Garage replication factor, broker `noeviction`) — see `apps/README.md`.

## Conventions and gotchas

- Every `kustomization.yaml` lists resources explicitly — a new file is not deployed until
  listed.
- **Adding an app**: the list is in `apps/README.md` (Adding an application).
- `apps/gaufre.js` / `apps/switcher.js` must not contain `$` (Calendars' ConfigMap is
  substituted over).
- updatecli patterns must be anchored to the repository URL: all git pins share
  `sources.yaml`, and an unanchored match rewrites the wrong app's tag.
- NetworkPolicy is rendered but not enforced (Flannel, adr/0103) — don't treat it as
  segmentation.
- A change that adds or reverses a design decision needs an ADR in `docs/adr/` (numbered
  from 0101; `docs/history/design/` is the original design set, still cited as
  `history/design/adr/000x`).
- Add user-facing changes under `## Unreleased` in `CHANGELOG.md`; `./release.sh <version>`
  turns it into the version section, bumps all four charts and the example tag, commits and
  tags (`docs/releasing.md`). Tags are immutable.

## Commits

`<gitmoji> (<scope>) <imperative subject>`, enforced by `.gitlint`: title ≤ 80 chars, body
wrapped at 92. E.g. `🐛 (valkey) let projects run INFO`. Not Conventional Commits.
