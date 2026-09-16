# office-platform

The platform, whole: the Flux-reconciled configuration, the charts that render it, and
the checks that keep both honest. Published by `release.sh` as one version — a config
artifact and four charts — and installed by an organisation from one file of its own
(`examples/cluster.yaml`). Design and decisions: `../platform-design/`, `docs/adr/`.

```
charts/
  control-plane/   the chart an organisation installs: renders the Flux control plane —
                   sources, cluster vars, one Kustomization per layer and per ENABLED app —
                   from ~10 typed, schema-checked values (platform-design/12)
  platform-lib/    library — names, labels, routes, netpol, pdb, oidc helpers
  platform-deps/   everything an app needs BEFORE it starts: datastores + secrets
  platform-app/    the surround: HTTPRoutes, NetworkPolicy, PDB, ServiceMonitor
examples/          cluster.yaml — the one file an organisation keeps, in a source of its own
infra/             operators (CNPG, ESO, the Garage operator)
platform/          shared stateful layer — gateway, postgres, valkey, search, keycloak, and
                   the datastores of every app whether enabled or not; objectstore/ is its
                   own layer so `objectStore.mode: external` can leave it out
apps/              one directory per application, each its own Flux Kustomization
apps/overlays/     the size profiles, applied to each app as a kustomize component
policy/            conftest rules — charts/ over what the charts render, config/ over the sources
tests/             every check below, and the cases and goldens they share
```

Reconcile order: `infra` → `platform` → `objectstore` → `app-<name>`, with the dependencies
between applications as `dependsOn` edges from the table in
`charts/control-plane/templates/_helpers.tpl`. Cluster singletons (the Gateway,
PriorityClasses, ClusterIssuers) are plain manifests in `platform/`, not a chart —
`docs/adr/0101`.

Nothing per cluster lives here. A cluster is a `cluster.yaml` in the organisation's own
source — ours are in `../clusters/` — and the `cluster-*` cases in `tests/cases/` are the
values files the checks build: prod's, demo's, and a minimal selection on external S3.

## Checks

Every job in `.github/workflows/pr.yaml` runs one of these, so the check that fails in CI is
the check you can run here. `tests/cases/index.yaml` is the list of rendered cases every
chart check iterates; a case added there is picked up by all of them.

| Command | Question it answers |
|---|---|
| `./tests/render.sh <case>` | what does this case render to? (the chart checks shell out to it) |
| `./tests/schema.sh` | do the schemas — and the control plane's refusals — still reject a bad values file? |
| `./tests/golden.py` | did this template change alter the output? `--update`, then read the diff |
| `./tests/equivalence.sh` | do the charts still reproduce the hand-written manifests they replaced? |
| `./tests/build.py [dir]` | does every layer of every cluster build, with no `${VAR}` left unresolved? |
| `./tests/kubeconform.sh [dir…]` | is what the charts render and what Flux would apply valid for the API server? |
| `./tests/render-diff.sh [base]` | what does this change do to what the clusters actually apply? |
| `./tests/binding.py [app]` | does our surround still attach to what the upstream charts create? |
| `./tests/profiles.py [size]` | do the size profiles still say what they claim to say? |
| `conftest verify --policy policy/charts` (and `policy/config`) | do the static rules still fire, both directions? |
| `conftest test --policy policy/charts --parser yaml --all-namespaces tests/golden/` | does the rendered output satisfy them? |
| `conftest test --policy policy/config --parser yaml --all-namespaces apps/ platform/ infra/ tests/golden/` | are the pins and remediation settings still as decided? |

`binding.py` and `profiles.py` fetch the pinned upstream charts, so they need network.
Everything else is offline. All of them render through `tests/render.py` — the control
plane with `helm template`, each layer with `flux build` — so what a check sees is what the
cluster applies, size profile and `../switcher.js` included.

Nothing here needs a cluster. What does — bootstrap-from-scratch, the upgrade test, the auth
smoke test, external-mode rotation — is nightly, and is not written yet.

## DNS

`./dns.py [cluster|cluster.yaml] [--check] [--zone]` prints the records a cluster needs, read
out of the config that will use them: the Gateway certificate's SAN list and every HTTPRoute
hostname, including the ones `platform-app` renders from `routes[].host`. `--check` resolves
each one and reports what disagrees.

Create them all *before* the first release: Let's Encrypt fails the whole certificate if a
single SAN fails validation, so one mispointed record is an outage for every application.

## Releasing

`./release.sh <version>` publishes the config artifact and the four charts under one
number; a cluster runs it by setting that number in its `cluster.yaml`, and rolls back by
setting it back. Published versions are immutable.

## Runbooks

`docs/bootstrap.md` — empty VM to a serving platform, with what is required and what is not.
`docs/gateway-cutover.md` — moving the public IP off an existing ingress controller.
`docs/control-plane-cutover.md` — moving a cluster from `clusters/<env>` onto the chart.

Licence: EUPL-1.2.
