# 0114 — A release is a git tag: clusters read the platform from the repository

**Status:** accepted · **Date:** 2026-10-07 · **Amends:** `release.sh`, `docs/releasing.md`

## Context
A version was published to an OCI registry as five artifacts — the config (`infra/`,
`platform/`, `apps/`) and the four charts — by `release.sh`, with the registry's robot
credentials, and every cluster pulled them with a pull Secret. For a public project that
is one more service to run and pay for, a credential on every release machine, and a
registry URL plus a Secret in every organisation's file — all to ship a 3 MB tree that
is already in the repository at the commit being released.

Flux reads both kinds of source natively. A `GitRepository` at a tag honours
`.sourceignore` as `flux push` did, and a `HelmChart` builds a chart from a path in it; a
HelmRelease's `chartRef` takes a `HelmChart`. The charts have no dependencies, so nothing
needs packaging. The platform cannot run without Flux, so `helm install oci://` for users
without it is no loss.

## Decision
A release is the tag `v<version>` on the commit that sets `<version>` in all four charts.
The organisation's `cluster.yaml` installs `charts/control-plane` from a `GitRepository`
at that tag. The control plane renders its own `GitRepository` (`office-config`) at
`v<appVersion>`, which the Kustomizations read and from which three `HelmChart`s build
`platform-deps`, `platform-app` and `platform-tenants`. `source: {url, secretRef}` is the
one knob: the public repository by default, a fork or a private copy otherwise.

The control plane does not reuse the organisation's `GitRepository`. A separate source at
its own version means the config moves only after the new control-plane templates have
been applied, as it did with OCI: a layer never arrives before the `cluster-vars` it reads.
The cost is a second fetch of the same tag.

## Consequences
- `release.sh` bumps, commits and tags; it publishes nothing and needs no credentials.
  `.github/workflows/release.yaml` checks a pushed tag against the charts.
- Immutability moved from `release.sh` refusing to re-push to a tag protection rule on
  `v*`. Without that rule a maintainer can move a tag, and a cluster pinned to it changes.
- `.sourceignore` no longer excludes `charts/`: the HelmCharts are built from the source.
- A private repository needs a read-only deploy key in a Flux git Secret, on the
  `platform` GitRepository and as `source.secretRef`.
- Every cluster fetches from the git host. Mirroring is a fork and a changed `source.url`.
