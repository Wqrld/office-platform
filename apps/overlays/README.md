# Size profiles

Three profiles — `small`, `medium`, `large` — selected per cluster by one value, `size`, in
its `cluster.yaml`. `history/design/05-app-contract.md` designed this; this file is what was actually
built, including the places it differs from the design.

## How it fits together

```
apps/<name>/                       one application, defined once
apps/overlays/size-<size>/         the profile: a Kustomize COMPONENT of patches
charts/control-plane/templates/apps.yaml
                                   one Flux Kustomization per enabled app:
                                   path: ./apps/<name>, components: [../overlays/size-<size>]
```

Same shape for `platform/`. The profile is applied to one app at a time, and that works
because kustomize no-ops a patch whose target is not in the render: one file per profile,
every number in exactly one place, and no selector directory per size and per app. The
cost is that a typo'd target is a silent no-op in *every* build rather than merely
invisible in the whole-set one — `tests/profiles.py` asserts every target matches an
object that renders.

`medium` is the identity profile: it patches nothing, because `apps/*/release.yaml` already
carries the measured production numbers, and restating them in an overlay would put every
figure in two places. `./measure.py compare` asserts that medium renders byte-for-byte what
no profile renders, which is what made switching prod onto the mechanism a no-op rather
than a migration.

## Two differences from the design

**A component, not a patch file.** `history/design/03-repo-layout.md` says `overlays/size-small.yaml`. A
plain patch file cannot hold both strategic-merge and JSON6902 entries, and Drive needs
JSON6902 — its `celeryWorkers` is a list, a merge patch replaces a list wholesale, and the
list carries the `probes` the chart dereferences without a nil guard. A merge patch there is
a render-time nil pointer, not a smaller worker. A Component keeps the one-file-per-profile
property with both patch kinds available.

**The profile covers the platform layer too.** The design set's table names CNPG instances
and Garage node counts as profile concerns but puts profiles only under `apps/`. An empty
demo pays for Postgres, two Valkeys, Garage and Keycloak before it serves a request, and
that floor is most of what decides whether a demo fits. `platform/overlays/` exists for the
same reason `apps/overlays/` does.

## The cost of adding an application, stated plainly

Adding an app is **one directory plus one stanza in `size-small`** (and in `size-large`, if
its replica knobs differ). It is not a single-file change, and it cannot be, for the reason
`history/design/00-start-here.md` #13 already records: the upstream charts share no values schema, so the
numbers can only be written where each chart spells them. An untargeted `kind: HelmRelease`
patch would be a silent no-op on every chart whose path differed.

What that buys, against the alternative: a per-environment copy of each app file would be
one new file per app **per environment**, and every future edit made in two places. One
stanza in one profile file is the smaller of the two, and it is visible — a missing entry
means an app runs at production size in a demo, which the totals below make obvious.

**The check worth having in CI**, now written: every HelmRelease in `apps/` that sets
`resources` anywhere has a matching entry in `size-small`. That is the failure this layout
can actually have, and it is a set difference, not a judgement call. `tests/profiles.py`
asserts it, alongside the replica/PDB pairing this file calls load-bearing — that one caught
three components scaled above one replica at `large` with no budget between them.

**The follow-up worth taking**: `platform-app` could emit each app's LimitRange from one
line in the surround it already renders, instead of the copy now sitting in each
`apps/*/namespace.yaml`. That is the version where the guardrail really is single-file.

## What a profile may not decide

- **Collabora's replica count.** One replica is correctness, not sizing: every viewer of a
  document must reach the pod holding it, which needs affinity on the `WOPISrc` query
  parameter, and Envoy Gateway's consistent hash cannot key on a query parameter. Two
  replicas is two divergent documents. Scaling it needs the chart's `reverseProxy` sidecar
  and a WOPI proof key — a design change, not a profile entry.
- **Drive's celery-beat replica count.** Two beats is two schedulers firing the same
  crontab; for Drive that is two WOPI reconfigurations racing every ten minutes.
- **Garage's `replication.factor`.** It cannot be changed in place. Moving an installation
  from `small` to `large` does not make its object store redundant — that is a rebuild.
- **Valkey's broker eviction policy.** `noeviction` at every size. Eviction on a broker is
  not a memory saving, it is silently dropped Celery tasks.

## Measured totals

`./measure.py render --size <size>`, 2026-09-05 (before Calendars, Meet and LiveKit).
Requests only — what the scheduler admits on.

| Profile | Platform | Apps (install peak) | Total peak | Total steady |
|---|---|---|---|---|
| `small` | 700m / 2,498Mi | 570m / 4,928Mi | **1,270m / 7,426Mi** | 1,020m / 5,058Mi |
| `medium` | 800m / 2,754Mi | 1,135m / 7,136Mi | **1,935m / 9,890Mi** | 1,435m / 6,434Mi |
| `large` | 8,550m / 30,402Mi | 8,235m / 18,656Mi | **16,785m / 49,058Mi** | — |

**Read the peak, not the steady state.** Docs' `migrate` and `createsuperuser` and Drive's
`migrate`, `createsuperuser` and `configure-wopi` Jobs each inherit `backend.resources` and
run alongside the workloads they are migrating for. Five Jobs is 250m/2,368Mi of the small
profile's peak — 44% of its memory. An environment sized to the steady state does not come
up, and it looks like a scheduling bug rather than a sizing one.

`large` is **not validated**: this platform has one node, its numbers are a shape rather
than a measurement, and 17 cores says so honestly.
