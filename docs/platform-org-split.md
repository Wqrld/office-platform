# The platform / organisation split

The product goal, stated as two acceptance criteria:

> A large platform codebase on public GitHub that gets updated every now and then, and for
> every organisation a separate folder where they configure it — **disable apps**, **use a
> different S3 provider.**

Both are built (§12 at the end is what was built and why it differs from the plan below).
`examples/cluster.yaml` is the organisation's whole file; `office-clusters/` holds ours.
Sections 1–11 are the plan as written on 2026-09-15; paths in them (`clusters/<env>/`,
`config/`, `helm-charts/`) are the pre-merge layout.

## 1 — What `clusters/<env>/` actually is

It is presented as the organisation's folder. It is not. Measured:

| File | Lines | Organisation-choosable values in it |
|---|---:|---|
| `sources.yaml` | 161 | 0 — upstream chart pins, the two commit-pin exceptions to `adr/0104` |
| `README.md` | 71 | 0 — how the two-tag release works |
| `flux-instance.yaml` | 32 | 0 — Flux components, `networkPolicy: false` per `adr/0103` |
| `config-source.yaml` | 25 | 1 — the version tag |
| `vars.yaml` | 19 | 5 — `BASE_DOMAIN`, `STORAGE_CLASS`, `GATEWAY_IP`, `TLS_ISSUER`, `LIVEKIT_IP` |
| `40-apps.yaml` | 18 | 1 — the size profile path |
| `30-platform.yaml` | 18 | *the same 1* — the size profile, restated |
| `20-infra.yaml` | 13 | 0 |
| **Total** | **357** | **7** |

**Seven values in 357 lines.** Handing an organisation a copy of this directory forks 350
lines of platform mechanics into every deployment. Adding a `10-crds` layer, bumping Docs to
v5.6.0, or changing a `timeout` then has to be hand-merged into N forks — the exact failure
the design exists to prevent, made worse by multiplication.

So the direction inverts. Almost all of `clusters/prod/` belongs **inside** the versioned
platform, not outside it.

## 2 — What the substitution mechanism can and cannot do

Three facts, each verified with `flux build kustomization --dry-run` before this plan was
written, because the whole design rests on them.

**Substitution reaches a nested `spec.path`.** A Kustomization emitted by a parent
Kustomization with `postBuild.substituteFrom` has its own fields substituted, `spec.path`
included:

```
path: ./environments/${SIZE}/apps   →   path: ./environments/medium/apps
```

So the size profile can be an organisation *value* rather than two hand-edited path lines.

**Substitution cannot add or remove a resource.** It is text replacement applied *after*
kustomize build. `${SIZE}` works only because the platform ships three prebuilt directories
and the variable selects one. The same trick does not extend to app selection: seven apps
are 128 subsets, and the platform is not going to ship 128 directories.

**`suspend` is not "disabled".** `suspend: ${DOCS_ENABLED}` substitutes cleanly and is a
trap — suspend stops reconciliation without pruning, so a "disabled" app keeps running.

The residue in plain Flux YAML is one Kustomization per app, instantiated by the
organisation — about nine lines of copy-paste each. That is the boilerplate this plan
exists to avoid.

**Conclusion: the control plane needs a conditional, and Flux has none. Helm does.**

## 3 — The architecture

Three things, in two repositories.

```
office-platform/  (public, versioned, OCI-published)
├── charts/
│   ├── platform-lib/                  # unchanged
│   ├── platform-deps/                 # unchanged
│   ├── platform-app/                  # unchanged
│   └── platform-control-plane/        # NEW — renders the control plane
│       ├── values.schema.json         #   the organisation's contract, validated
│       └── templates/
│           ├── cluster-vars.yaml      #   the ConfigMap, DERIVED from typed values
│           ├── sources.yaml           #   today's sources.yaml, with registry values
│           ├── layers.yaml            #   20-infra, 30-platform
│           └── apps.yaml              #   one Kustomization per ENABLED app
├── infra/  platform/  apps/  environments/     # unchanged
└── examples/cluster.yaml              # what an organisation copies

<org>-cluster/  (private, per organisation, ~25 lines)
└── cluster.yaml
```

The organisation's repository is **separate from the platform artifact**. That separation is
load-bearing — see §6.

## 4 — The organisation's file, in full

```yaml
# 1. Flux manages itself. Applied once by hand at bootstrap; reconciled from here after.
apiVersion: fluxcd.controlplane.io/v1
kind: FluxInstance
metadata: {name: flux, namespace: flux-system}
spec:
  distribution: {version: "2.x", registry: ghcr.io/fluxcd}
  sync:
    kind: GitRepository
    url: https://github.com/example-org/cluster
    ref: main
    path: .
---
# 2. The platform version. THIS LINE IS THE UPGRADE.
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata: {name: platform, namespace: flux-system}
spec:
  interval: 30m
  url: oci://ghcr.io/<org>/office-platform/control-plane
  ref: {tag: "2.0.0"}
---
# 3. Everything this organisation chooses.
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: {name: platform, namespace: flux-system}
spec:
  interval: 30m
  chartRef: {kind: OCIRepository, name: platform}
  values:
    domain: example.org
    storageClass: longhorn
    gateway: {ip: 10.0.0.5, tlsIssuer: letsencrypt}
    size: medium
    apps:
      docs: true
      drive: true
      collabora: true
      find: true
      calendars: true
      meet: false            # also drops livekit, which nothing else needs
    objectStore:
      mode: external         # or `garage`, the default
      endpoint: s3.example.org
      region: eu-west-1
      credentialSecret: s3-creds
```

About twenty lines of frame around eight lines of choices. The frame cannot shrink further
without hiding the version pin, which should stay visible.

Both acceptance criteria are met by that values block, and `values.schema.json` makes it a
*validated* surface: a typo is a rejected HelmRelease with a message, not a silently
unresolved `${BASE_DOMIAN}` serving to nobody.

## 5 — Why a chart and not more substitution variables

`vars.yaml` grew from four scalars to five (`LIVEKIT_IP`) during the week this was written.
A flat `${ALL_CAPS}` namespace has no schema, no types, no defaults documentation, and no
way to reject a misspelling. Every new knob — `${S3_MODE}`, `${S3_ENDPOINT}`,
`${S3_REGION}` — widens it. Typed values with a schema are the same information with a
contract attached, and the repository already has the habit: `platform-deps` and
`platform-app` both ship `values.schema.json`.

`cluster-vars` does not disappear. The platform still substitutes `${BASE_DOMAIN}` into
HTTPRoutes internally, so the ConfigMap is still rendered — **by the chart, from
`.Values.domain`**. One typed input, one derived artifact, nothing written twice.

**The costs, stated plainly.** The control plane becomes Go templates, which are less
greppable than the eight plain YAML files it replaces. And helm-controller must be running
before the control plane renders, so the control plane cannot be the thing that installs
Flux — the FluxInstance stays a hand-applied bootstrap object, as it already is.

## 6 — Where the organisation's configuration lives

**Decided: in a source the organisation owns, never inside the platform artifact.**

It does not have to be a *repository*. Flux will sync a `GitRepository`, a private OCI
artifact, or a `Bucket`, and the platform should not care which — `examples/cluster.yaml`
shows a git repo because it is the one every organisation already knows how to run. What
matters is only that it is not a directory inside the public platform repo. Three reasons,
heaviest first:

1. **It is the only shape that generalises.** A second organisation cannot commit its domain
   and its IP addresses to someone else's public repository. If `clusters/<org>/` stays in
   `office-platform`, the public repo becomes a directory of other people's clusters and the
   "separate folder per organisation" is a fiction maintained by whoever holds push rights.
2. **It is what dissolves the two-tag split** — see below.
3. **Operational detail stays the organisation's to disclose.** Addresses, which apps they
   run, how much they provision. None of it is the platform's to publish.

For this deployment that means one new small private repository holding the `cluster.yaml`
from §4. The platform ships `examples/cluster.yaml` as the thing to copy.

### The consequence: `config-source.yaml` and the `:latest` / `:X.Y.Z` split disappear

That file's entire rationale is that `flux-instance.yaml` lives inside the path it syncs, so
pinning it deadlocks — the pointer to a new version would live inside the version Flux is
not yet pulling. Once the FluxInstance lives in the organisation's own source and the
platform pin lives in a different object backed by a different registry, the cycle cannot
form. Twenty-five lines of subtle machinery, `release.sh`'s dual-push, and a discipline that
has to be explained to every reader: all unnecessary.

Note how tightly this is coupled to the decision above. Put the organisation's folder back
inside the platform repo and the deadlock returns with it.

Also removed: `clusters/` as a concept — there is no per-cluster directory any more — and
the size-profile path duplicated across `30-platform.yaml` and `40-apps.yaml`.

## 7 — Disabling an app: what actually happens

**Decided: remove the service from the cluster, keep the data.** This needs almost no new
mechanism, because `adr/0107` already put everything durable outside the app's namespace.

When `apps.meet: false` stops the control-plane chart emitting the `app-meet` Kustomization,
the parent prunes it, and its own `prune: true` removes everything it applied — the
`office-meet` namespace and its contents. What that reaches, and what it does not:

| Thing | Lives in | On disable |
|---|---|---|
| Deployments, Services, HTTPRoutes, NetworkPolicies | app namespace | **deleted** — this is the point |
| ESO-materialised credential Secrets | app namespace | deleted; they are copies |
| Postgres `Database` + `DatabaseRole` | `platform/postgres/databases.yaml` (30-platform) | **untouched** |
| The generated role password | `office-data`, `refreshInterval: "0"` | **untouched** |
| Valkey and OpenSearch users | `platform/secrets/` (30-platform) | **untouched** |
| Garage bucket contents | app-namespaced CR, `deletionPolicy: Retain` | CR deleted, **contents retained** |
| `meet-whisperx-models` PVC | app namespace | deleted — a model cache, re-downloaded in minutes |

Data survives by construction, not by a new feature. The only app-namespaced PVC in the
entire tree holds a regenerable model cache, and `deletionPolicy: Retain` is already the
default in `platform-deps/values.yaml`. Re-enabling re-materialises the same password from
the same generate-once Secret and reconnects to the retained database, so an app comes back
with its content rather than empty.

**The deliberate non-change:** 30-platform stays whole-set. It provisions datastores for
every application the platform knows about, enabled or not. That is what makes the table
above true, and it is also the cheapest thing to build, because it is what the tree already
does. The cost is an empty database and an unused role for an app an organisation never
enables — a few kilobytes and a row in `\du`, weighed against making disable destructive.

**What is therefore not offered:** there is no "disable and also delete my data" switch. An
organisation that genuinely wants a bucket gone removes it by hand, deliberately. Putting
destruction behind a boolean in a config file is how people lose data at 02:00.

## 8 — The one genuinely hard part: per-app layers

Today `apps/kustomization.yaml` is one flat list of 35 resources whose ordering comments
encode real dependencies (Collabora before Drive, Find before Docs, LiveKit before Meet).
Per-app enable/disable requires splitting it into `apps/<name>/kustomization.yaml`, with
those dependencies becoming Flux `dependsOn` edges the control-plane chart emits.

That is a real improvement — dependencies become declared and health-gated rather than
implied by file order — and it is the largest change in this plan.

**The size profiles survive the split intact**, which was not obvious. A component's patches
are name-targeted, and *kustomize silently no-ops a patch whose target matches nothing*
(verified). So the same one-file-per-profile component can be applied to a single app's
directory: one patch matches, the rest do nothing. The property `size-medium`'s header
defends — one file per profile, numbers in exactly one place — is preserved.

**The hazard that creates.** Silent no-op now applies to app names too, so a typo'd target
in `size-small` becomes undetectable rather than merely invisible. Mitigation, using
machinery that already exists: assert that the union of the per-app renders is byte-identical
to the whole-set render, the same way `measure.py compare` already asserts that `medium` is
the identity profile.

## 9 — Sequence

Each stage ends with something that runs, and none of the first three changes what is
deployed.

### S1 — Split `apps/` per application

`apps/<name>/kustomization.yaml` per app; `environments/<size>/apps/<name>/` selecting the
base plus the size component; the `configMapGenerator` entries move to the apps that own
them. No control-plane change; `40-apps.yaml` still points at one path.

**Done when:** the union of per-app renders is byte-identical to today's whole-set render,
asserted by a test, and `build.sh` / `kubeconform.sh` / `conftest` pass unchanged.

### S2 — Write `platform-control-plane`

The chart renders exactly what `clusters/prod/` contains today, from values that encode
today's choices. Goldens per the `tests/golden.py` convention.

**Done when:** `helm template` with prod's values produces output byte-identical to
`clusters/prod/`, modulo key ordering.

### S3 — Cut prod over

Publish the chart, create the organisation repository, point prod's FluxInstance at it,
delete `clusters/`.

**Done when:** prod reconciles from the new control plane with no drift, and `release.sh`
has lost its dual-push.

### S4 — Build the two capabilities

`apps.<name>` conditionals in the chart; `objectStore.mode: external` in `platform-deps`,
whose `templates/objectstore.yaml` currently emits `GarageBucket` and `GarageKey`
unconditionally.

**Done when:** the demo cluster runs with an app disabled and an external S3 endpoint,
neither having required an edit to a file the platform ships — and a disable/re-enable round
trip brings the app back with its documents intact, which is the test that §7's table is
true rather than merely argued.

## 10 — Open decisions

| Question | Bearing |
|---|---|
| Public registry for the control-plane chart (ghcr.io vs Harbor) | Organisations outside this Harbor cannot pull today |
| Does `size` stay a kustomize overlay, or become chart values? | Values would delete `environments/` entirely; larger change, deferred past S4 |

## 11 — What would make this plan wrong

If organisations turn out to need to change things the values schema does not anticipate,
the chart becomes a bottleneck: every organisation-specific need is a platform release. The
mitigation is an escape hatch — an `extraKustomizations` value letting an organisation add
its own layer from its own source — but that should be added when a second organisation asks
for it, not before (P6).

## 12 — As built (2026-09-16)

All of it is live: the cutover ran on 2026-09-16 (prod was rebuilt on 2.0.1 after it —
`PROGRESS.md`, Incidents). The two repositories of §3 are real: `office-platform/` is the
platform (`config` and `helm-charts` merged) and `office-clusters/` is the organisation's.
Where what was built differs from the plan above, this is why:

| Plan | Built | Reason |
|---|---|---|
| `charts/platform-control-plane` in a merged repo | `charts/control-plane` in the merged repo | As designed: one public repository, one organisation file. `release.sh` publishes the config artifact and the charts under **one version**, and the control plane pins the charts and the artifact at its own `.Chart.Version` — the organisation's chart pin is the platform version, and nothing is ever bumped by hand to agree with it |
| `environments/<size>/apps/<name>/` — 21 selector directories | none; the chart emits `path: ./apps/<name>` plus `components: [../overlays/size-<size>]` | Flux `Kustomization.spec.components` applies the profile as a component, verified byte-identical to the overlay render. `environments/` is deleted |
| `objectStore: {endpoint, region, credentialSecret}` as values | `objectStore: {mode}` only; endpoint, region and credentials in a hand-applied `object-store` Secret in `office-data` | The SMTP relay already works this way ("switching provider is one `kubectl` and nothing about mail is in git"); one precedent, not two. `apps/*/deps.yaml` gains one line, `mode: ${S3_MODE}`, not four |
| Garage stays in 30-platform | `platform/objectstore/` is its own layer, emitted only in `garage` mode | Substitution cannot remove a resource; a layer can be left out. The operator stays in `infra` (its CRDs are what make the CRs applicable) — one idle Deployment in external mode |
| "union of per-app renders == whole-set render" as the profile test | `tests/profiles.py` asserts every profile patch target matches a rendered object | The union test passes on a typo'd target — both renders lack the patch. The direct assertion is what catches it |
| Layer names `20-infra`, `30-platform`, `40-apps` | `infra`, `platform`, `objectstore`, `app-<name>` | Order is now declared by `dependsOn`, and new names make the cutover collision-free |

Two things worth knowing. The Certificate's SAN list follows the selection: the app table
also carries each app's `hosts`, the chart emits them as one JSON list in `TLS_HOSTS`, and
`certificate.yaml` says `dnsNames: ${TLS_HOSTS}` — Flux substitutes on the YAML text, so a
variable can stand in for a list (verified with `flux build`'s own postBuild), which is the
one place §2's "cannot remove" has a way round. A disabled app has no SAN and needs no
record; `s3.*` is a SAN only in Garage mode. And `livekit` is not an organisation toggle:
it is `internal: true` in the app table and follows `meet`. Dependencies are enforced at render
(`apps.drive needs apps.collabora, which is off`), as are unknown keys and bad addresses.

Open from §10, unchanged: the public registry. Everything is published to Harbor; the
`registry` values make the chart portable, the organisation's `cluster.yaml` names it.
