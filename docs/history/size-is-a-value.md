# Size is a value, not a patch — design

**Built 2026-09-21**, as below, with two deviations: the upstream releases keep
`pdb: {enabled: false}` (the surround owning budgets is not a size) and `replicas: 0` (not
deployed is not a size); and `meet-whisperx` is neither a chart nor a patch but one size at
every profile — `apps/meet/README.md` says why. The surround's PDB block moved too, as
`sizes/platform-<size>.yaml`, since `large` set it. What follows is the design as written.

`apps/overlays/size-*/` sizes each application by patching Helm values inside a HelmRelease
inside a Flux Kustomization — three merge semantics stacked. It is the one place the layout
fights the tooling, and everything around it is scaffolding built to survive that:
`tests/profiles.py` exists mainly to catch a patch that silently misses, `measure.py
compare` asserts that `medium` is still the identity, and `apps/overlays/README.md` opens
with a section on where the mechanism differs from the design. This makes size a value the
chart receives, delivered the way Flux delivers values.

**Shape.** Every number an app needs at a size lives in one file per size, next to the app,
in the chart's own values shape. `release.yaml` carries no sizing at all.

```
apps/docs/
  release.yaml             valuesFrom the sizes ConfigMap; no resources, replicas, concurrency
  sizes/small.yaml         only the sizing keys, in the upstream chart's own values shape
  sizes/medium.yaml        the measured production numbers, stated — no longer the identity
  sizes/large.yaml
  kustomization.yaml       configMapGenerator: docs-sizes {small=…, medium=…, large=…}
```

```yaml
# apps/docs/release.yaml
spec:
  valuesFrom: [{kind: ConfigMap, name: docs-sizes, valuesKey: "${SIZE}"}]
```

`SIZE` is one more line in `cluster-vars`; the control plane already has it as
`.Values.size`. `spec.values` wins over `valuesFrom`, so a sizing key left in `release.yaml`
would silently beat every profile — `tests/profiles.py` keeps one set difference: no
`resources`, `replicas` or `pdb` key anywhere under `spec.values` in `apps/*/release.yaml`.

**What that buys.**

- A wrong size name is a missing ConfigMap key: the HelmRelease is not Ready and says so.
  A wrong value path is Helm's problem, the same as any other value. The silent-no-op class
  of failure — an app running at production size in a demo because a patch target was
  typo'd — no longer exists, so nothing has to check for it.
- All three sizes in one shape in one place. `medium` stops being "whatever `release.yaml`
  says", so adding an app is one directory again, and the README stops needing to explain
  that a `small` entry is a diff against another file.
- No Components, no JSON6902, no `../overlays` reaching out of the app directory. The
  control plane's `apps.yaml` template drops `components:`.

**What it costs.**

- Helm merges lists by replacement, same as a strategic-merge patch. Drive's
  `celeryWorkers[0]` carries the probes the chart dereferences with no nil guard, so the
  whole element is restated in all three size files — plain values three times instead of
  one JSON pointer. The fix is upstream: a `resources` default the list inherits
  (`adr/0108`).
- `meet-whisperx` is a bare Deployment, the only non-chart workload. Either its patch
  stays (one Component for one Deployment) or it becomes a thirty-line chart. Chart: it is
  already the special case in every profile file, and a chart gives it `valuesFrom` like
  the rest.
- `platform/overlays/` stays as patches. CNPG instances, Garage nodes and Keycloak
  replicas are plain manifests, not HelmReleases, and there are three targets, not thirty.

**Lines.** Roughly −350 net, on a mechanism of about 1,000 today. The numbers do not
shrink, they move; what disappears is patch scaffolding (~140 lines of
`target`/`apiVersion`/`kind`/`metadata`/`spec`/`values` wrappers), the comments explaining
the scaffolding (~105), the two `profiles.py` checks that police it (~60), `measure.py
compare` (~20) and most of `apps/overlays/README.md` (~70). What comes is ~410 lines of
size files — the ~350 numbers plus medium's ~110 made explicit — Drive's list twice more
(~40), and seven `valuesFrom` + `configMapGenerator` stanzas (~35).

**Order of work.**

1. Land after `REVIEW.md` §3 phase 2, so one release is not two migrations.
2. Per app, in one commit: move the sizing keys out of `release.yaml` into
   `sizes/medium.yaml`, translate the `small` and `large` patches into `sizes/small.yaml`
   and `sizes/large.yaml`, add the generator and `valuesFrom`. `./tests/render-diff.sh`
   must show an empty diff for `cluster-prod` and `cluster-demo` (both `medium`) before
   the commit is done, and the `small` and `large` cases in `tests/cases/` must render
   the same workloads they did — `golden.py --update`, then read the diff for numbers only.
3. Delete the three Components, `components:` in `apps.yaml`, `every_target_matches` and
   `small_profile_covers_every_app` in `profiles.py`, `measure.py compare`. Rewrite
   `apps/overlays/README.md` as `apps/README.md`'s sizing paragraph.
4. `SIZE` in `cluster-vars`; the schema already restricts `size` to the three names.
5. Demo first. A HelmRelease that goes not-Ready on "key not found" is the new failure and
   the one to see once on purpose.

**Not changed.** The invariants worth keeping in `profiles.py` — `replicas > 1` implies a
PDB that selects those pods, `replicas == 1` implies none does, every PDB uses
`maxUnavailable`, Garage's `replication.factor` identical across sizes — are about what a
size *means*, not about how it is delivered, and they stay.
