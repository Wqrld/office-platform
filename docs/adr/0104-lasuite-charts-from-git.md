# 0104 — La Suite charts are consumed from git refs, not a Helm repository

**Status:** accepted · **Date:** 2026-09-02 · **Corrects:** design set `adr/0104`

## Context
`adr/0104` — the discovery the whole rebuild rests on — is that DINUM maintains Helm charts
for most La Suite applications, so we consume them and build only the surround. The design
set's app contract accordingly uses `sourceRef: {kind: HelmRepository, name: suitenumerique-docs}`.

**There is no such Helm repository.** Verified 2026-09-02: `suitenumerique.github.io/helm-charts`
returns 404, the org has no `helm-charts` repository, and no chart is published to an OCI
registry. Each application ships its chart *in-tree*, at `src/helm/<name>` in its own git
repository, deployed upstream via helmfile.

## Decision
Consume the charts through a Flux `GitRepository` source pinned to a release tag, with
`chart.spec.chart` set to the in-repo path:

```yaml
sourceRef: {kind: GitRepository, name: suitenumerique-docs}
chart: src/helm/impress          # note: path is `impress`, chart name is `docs`
```

## Reasoning
The *conclusion* of `adr/0104` survives intact — the charts exist, are maintained, and are
worth consuming; only the transport was wrong. A pinned git tag preserves P1 ("publish the
base, don't copy it"): we reference an immutable upstream ref rather than vendoring files
into our repo, and an upgrade remains a version bump plus a render-diff.

## Consequences
- Chart versions do not move independently of app releases, so **the git tag is the pin** —
  `image.tag` must still be pinned separately, as the design already requires.
- No `helm repo` semver ranges. Dev clusters track a branch; prod pins a tag.
- Upstream can break a chart between tags with no version signal. The render-diff on bump and
  the binding check (`history/design/10-verification.md`) are the compensating controls, and are now
  load-bearing rather than nice to have.
- **One app has no tag to pin.** `suitenumerique/find` has never cut a release — zero git
  tags, and one floating `main` image — so it is pinned to a **commit** instead, with the
  image pinned by digest through a post-renderer. That is a narrow exception, not a second
  default: every other app pins a tag. It also removes the last version signal, which makes
  the two compensating controls above the only ones Find has. Retire the exception the day
  upstream tags a release. See `apps/find/README.md`.
- **One app has a chart that is not in any tag yet.** `suitenumerique/calendars` ships its
  chart at `src/helm/calendars` exactly as this ADR expects, but it was written after the
  `v0.1.0` tag and the upstreaming PR is still open. Pinning `main` is denied by
  `policy/pins.rego`, correctly, and making a second commit-pin exception of Find's
  would turn an exception into a pattern. So that chart is packaged and served from our own
  Helm repository and consumed as an ordinary versioned chart, which costs nothing
  architecturally: when the PR lands, the source becomes a `GitRepository` at a tag and the
  only other change is `chart.spec` in the release. Unlike Find's, this exception has a
  known end. See `apps/calendars/README.md`.
