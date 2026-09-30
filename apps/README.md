# apps/

One directory per application, each its own Flux Kustomization (`app-<name>`, emitted by
the control plane for every enabled app). Three releases per app, in order:

| File | Release | What it is |
|---|---|---|
| `deps.yaml` | `<app>-deps` (platform-deps) | everything the app needs before it starts: datastore Secrets, OIDC client, bucket, generated and shared tokens |
| `release.yaml` | `<app>` (the upstream chart) | the application, with the platform's Secrets wired in |
| `surround.yaml` | `<app>-platform` (platform-app) | what goes around it: routes, traffic policies, NetworkPolicy, PDB, media proxy, static files |

Secrets must exist before the workload that reads them, so they cannot come from the
surround; the surround attaches to workloads, so it cannot come first. LiveKit and
Collabora skip what they do not need.

Every `kustomization.yaml` lists its resources explicitly: dropping a file into a directory
must not silently deploy it. `../namespace.yaml` is shared — `${APP}` is substituted per
Kustomization.

`networkPolicy` is on by default and NOT enforced on this cluster (adr/0103): Flannel ships
no policy controller. The egress graph is written down so it starts working the day a
policy-capable CNI arrives; do not cite it as segmentation.

## The switcher

One service list, one panel, four buttons. `charts/control-plane/apps.yaml` gives each
user-facing app a `switcher` entry; the control plane renders the enabled ones into
`SERVICES_JSON`, which `../services.yaml` puts in every app's namespace as `office-services`,
served from the app's own origin as `/custom/services.json`. An app that is off is in no
switcher; a link that resolves nowhere is a table entry that is wrong.

`gaufre.js` is the panel — a drop-in for the lasuite widget script that Docs' and Calendars'
`LaGaufreV2` load by URL (their defaults are the French government's CDN). `switcher.js` is
the button for Drive and Meet, whose frontends have none we can use; it hands the button to
`gaufre.js` over the widget's queue protocol. Docs, Drive, Calendars and Messages serve
both files through the surround's `staticFiles`; Meet's own nginx serves them (`apps/meet/default.conf`).
Projects' own `LaGaufreButton` speaks the widget's older dialect (`_stmsg_widget`, a
`toggle` command, no button element) and loads `<dir>/lagaufre.js`, so `gaufre.js` handles
both queues and Projects serves it under that key. Neither script may contain a dollar sign:
Calendars' ConfigMap is substituted over.

## Sizing

Three sizes — `small` (5-50 people, one node), `medium` (50-500, the measured one), `large`
(500-5,000, HA) — selected per cluster by one value, `size`, in its `cluster.yaml`. Every
app carries its own three, in the upstream chart's own values shape, and nothing else:

```
apps/<app>/sizes/<size>.yaml            the app's release: replicas, resources, concurrency
apps/<app>/sizes/platform-large.yaml    the surround: the disruption budgets (small and medium
                                        have none: ../sizes-no-pdb.yaml, shared)
apps/<app>/kustomization.yaml           configMapGenerator: <app>-sizes, one key per file
release.yaml / surround.yaml            valuesFrom: {name: <app>-sizes, valuesKey: "${SIZE}"}
```

`SIZE` is in `cluster-vars`, from the control plane's `size`. A size the ConfigMap lacks is
a HelmRelease that is not Ready and says which key is missing; a wrong value path is Helm's
problem, the same as any other value. `spec.values` beats `valuesFrom`, so **no sizing key
may live in `release.yaml` or `surround.yaml`** — `tests/profiles.py` asserts that, and
that every sized release has every size. (`pdb: {enabled: false}` in an upstream release is
not sizing: the surround owns budgets at every size, `tests/binding.py` fails a PDB from an
upstream chart. `replicas: 0` is a workload not deployed.)

Helm merges lists by replacement, so a list that carries a size — Drive's `celeryWorkers`,
with the probes the chart dereferences with no nil guard — is restated whole in each size
file. The fix is upstream (adr/0108).

`platform/overlays/size-<size>/` still sizes the platform layer as a kustomize component:
CNPG instances, Garage nodes and Keycloak replicas are plain manifests, three targets, not
thirty. `meet-whisperx`, the one workload that is not a chart, is one size at every profile
(`apps/meet/README.md`).

**What a size may not decide.** Collabora's replica count (one is correctness: every
viewer of a document must reach the pod holding it, and Envoy's consistent hash cannot key
on the `WOPISrc` query parameter); the SFU's (its media ports are per node, one address
fronts one pod); Drive's celery-beat (two beats is two schedulers firing the same crontab);
Garage's `replication.factor` (cannot be changed in place — a rebuild, not a size); the
broker's eviction policy (`noeviction` at every size, or Celery tasks are silently dropped).

**Measured totals** — `./measure.py render --size <size>`, 2026-09-05, before Calendars,
Meet and LiveKit. Requests only, which is what the scheduler admits on.

| Size | Platform | Apps (install peak) | Total peak | Total steady |
|---|---|---|---|---|
| `small` | 700m / 2,498Mi | 570m / 4,928Mi | **1,270m / 7,426Mi** | 1,020m / 5,058Mi |
| `medium` | 800m / 2,754Mi | 1,135m / 7,136Mi | **1,935m / 9,890Mi** | 1,435m / 6,434Mi |
| `large` | 8,550m / 30,402Mi | 8,235m / 18,656Mi | **16,785m / 49,058Mi** | — |

**Read the peak, not the steady state.** Docs' `migrate` and `createsuperuser` and Drive's
`migrate`, `createsuperuser` and `configure-wopi` Jobs each inherit `backend.resources` and
run alongside the workloads they are migrating for — 44% of the small profile's memory. An
environment sized to the steady state does not come up, and it looks like a scheduling bug
rather than a sizing one. `large` is **not validated**: one node, so its numbers are a
shape rather than a measurement, and 17 cores says so honestly.
