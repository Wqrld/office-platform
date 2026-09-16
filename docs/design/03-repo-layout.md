# 03 — Repository layout

Two repositories. The split *is* the architecture: one is versioned and published, the other
is thin and environment-specific.

## `platform` — released as OCI artifacts

```
platform/
├── charts/
│   ├── platform-app/                 # the surround — routes, netpol, PDB, metrics
│   │   ├── Chart.yaml                #   dependencies: [platform-lib]
│   │   ├── values.yaml
│   │   ├── values.schema.json
│   │   └── templates/main.yaml       # ~10 lines of includes
│   │
│   ├── platform-deps/                # datastores + the secrets an app needs at startup
│   │   ├── values.schema.json        #   oneOf on .kind; required-if on .mode
│   │   └── templates/
│   │       ├── postgres.yaml         #   CNPG Database + Role + extensions
│   │       ├── valkey.yaml
│   │       ├── garage.yaml           #   GarageBucket + GarageKey
│   │       ├── opensearch.yaml
│   │       ├── external.yaml         #   any kind, mode: external
│   │       ├── oidc-secret.yaml      #   the 22 OIDC_* vars, for envFrom
│   │       ├── secret-normalise.yaml #   ESO ExternalSecret → canonical shape
│   │       └── preflight-job.yaml
│   │
│   ├── platform-infra/               # cluster singletons
│   │   └── templates/{gateway,priorityclasses,clusterissuer}.yaml
│   │
│   ├── platform-lib/                 # type: library — ~250 lines
│   │   └── templates/
│   │       ├── _helpers.tpl          #   names, labels, selectors
│   │       ├── _httproute.tpl
│   │       ├── _networkpolicy.tpl
│   │       ├── _pdb.tpl
│   │       ├── _observability.tpl
│   │       ├── _oidc.tpl
│   │       ├── _workload.tpl         #   used only by mb-* charts
│   │       └── _jobs.tpl             #   used only by mb-* charts
│   │
│   ├── mb-calendars/                 # no upstream chart exists
│   └── mb-bureaublad/                # our own application
│
├── policy/                           # Kyverno — the invariant layer (adr/0013)
│   ├── mutate-security-context.yaml
│   ├── mutate-labels.yaml
│   ├── mutate-topology-spread.yaml
│   ├── validate-pdb.yaml
│   ├── validate-resources.yaml
│   └── validate-images.yaml
│
├── tests/{cases,golden}/
├── docs/{adr,adding-an-app.md,upgrading.md}
├── .github/workflows/{pr,release}.yaml
└── Makefile
```

## `config` — thin, per environment

```
config/
├── clusters/
│   ├── prod/
│   │   ├── flux-system/           # bootstrap output — never hand-edit
│   │   ├── sources.yaml           # OCIRepositories (ours) + HelmRepositories (upstream)
│   │   ├── vars.yaml              # ConfigMap: domain, storageclass, sizes, tenant
│   │   ├── 10-crds.yaml           # Kustomization
│   │   ├── 20-infra.yaml          #   dependsOn: crds
│   │   ├── 30-platform.yaml       #   dependsOn: infra
│   │   └── 40-apps.yaml           #   dependsOn: platform
│   └── dev/
│       ├── sources.yaml           # semver ranges instead of pins
│       └── ...                    # same four Kustomizations
│
├── infra/                         # operators, shared by all clusters
│   ├── crds/kustomization.yaml    # reconciled first, on its own
│   ├── cloudnative-pg.yaml
│   ├── garage-operator.yaml       # webhooks: needs cert-manager first
│   ├── envoy-gateway.yaml
│   ├── keycloak-operator.yaml
│   ├── external-secrets.yaml
│   ├── cert-manager.yaml
│   ├── external-dns.yaml
│   ├── kube-prometheus-stack.yaml
│   ├── grafana-operator.yaml
│   └── kyverno.yaml
│
├── platform/                      # shared stateful layer
│   ├── keycloak/                  # Keycloak CR + realm + client definitions
│   ├── gateway/                   # platform-infra release + Certificate
│   ├── postgres/                  # shared CNPG Cluster + Pooler + backup config
│   ├── valkey/                    # shared cache + shared broker (two instances)
│   ├── garage/                    # shared GarageCluster
│   └── opensearch/                # shared search
│
├── apps/
│   ├── namespaces.yaml            # one Namespace per app, with PSA labels
│   ├── docs.yaml                  # 3 HelmReleases in one file:
│   │                              #   deps (datastores + OIDC secret)
│   │                              #   · upstream chart · surround
│   ├── ...                        # ×14
│   ├── components/                # Kustomize components — one per optional app
│   │   ├── ollama/                #   a cluster opts in by listing the component
│   │   ├── conversations/
│   │   └── find/
│   ├── kustomization.yaml         # the apps every cluster runs
│   └── overlays/
│       ├── size-small.yaml        # 5-50 people
│       ├── size-medium.yaml       # 50-500
│       └── size-large.yaml        # 500-5000
│
└── secrets/.sops.yaml
```

**Namespaces are objects too.** Each app namespace carries the Pod Security Admission
labels (`pod-security.kubernetes.io/enforce: restricted`) and the label the shared Gateway's
`allowedRoutes.namespaces.selector` matches. They live in the `40-apps` Kustomization ahead
of the releases, not implicitly created by Flux.

**Not every cluster runs every app.** Ollama is optional wherever an external LLM endpoint is
used, Conversations is pointless without one, Find may be off in a `small` install, and
ClamAV is deferred. Kustomize cannot cleanly *remove* a resource an overlay inherited, so
optional apps are **Kustomize components**: not in the base `kustomization.yaml`, listed by
the clusters that want them. Opting in is one line in `clusters/<env>/40-apps.yaml`.

**Apps are defined once, not per environment.** Differences arrive two ways:

- **Scalars** via Flux `postBuild.substituteFrom` against that cluster's `vars.yaml`
  (`${BASE_DOMAIN}`, `${STORAGE_CLASS}`, `${TENANT}`).
- **Structure** via `overlays/`, one file per size profile, targeting `kind: HelmRelease`.
  "One replica, no PDBs, no HPA" is one file per profile covering every app — never a
  per-app-per-env file. This is what prevents overlay sprawl, and it is also how the
  5-to-5,000-person range is carried (`05-app-contract.md`).

## On Kustomize

Four things here say "kustomize"; only one is the pattern to avoid.

1. **Flux's `Kustomization` CRD** — badly named. It is Flux's unit of reconciliation:
   `dependsOn`, health checks, pruning, substitution, SOPS decryption. Mandatory, and not
   "using Kustomize" in the meaningful sense.
2. **`kustomization.yaml` resource lists** — explicit file manifests. Optional, but keeping
   them means dropping a file in a directory does not silently deploy it.
3. **`overlays/*.yaml`** — real Kustomize, deliberately, for cross-cutting env differences.
4. **`postRenderers.kustomize.patches`** — real Kustomize, as the per-release escape hatch.

**Rejected:** authoring apps in Kustomize. Fifteen apps × four environments × a dozen
resources, where every new field means touching sixty files, with no schema and silent
no-op patches.

**The rule:** Kustomize is a *patch* layer, not a *composition* layer. Helm generates;
Kustomize edits the result, only for what Helm is bad at.

## Naming and tenancy

Every resource name, label and hostname is qualified by a `${TENANT}` substitution variable
from day one, even while only one tenant exists. See `adr/0008-tenancy.md`. The cost today
is one variable and a convention; retrofitting it later is what kills.

Concretely, the mechanism is **the Helm release name and the namespace**, because those are
the only handles we have on resources an upstream chart generates — `${TENANT}` cannot reach
inside DINUM's templates. So a release is named `${TENANT}-docs` in namespace
`${TENANT}-docs`, upstream names inherit the prefix, and the surround's component selectors
match `app.kubernetes.io/instance: ${TENANT}-docs`. Anything a chart hardcodes without the
release name is a per-app finding. Say this plainly rather than claiming every resource name
is qualified: what is qualified is everything a release name reaches.
