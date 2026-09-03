# updatecli

Weekly upstream version bumps, opened as one pull request for review. Nothing here talks
to the cluster; it only edits pins in this repository.

    updatecli diff  --config updatecli/updatecli.d --values updatecli/values.yaml
    updatecli apply --config updatecli/updatecli.d --values updatecli/values.yaml

Run both from the repository root — target paths are relative to the working directory.
`diff` is read-only. On an up-to-date tree both report `Changed: 0, Failed: 0`.

## What it covers

| Pin | File | Driven by |
|---|---|---|
| cloudnative-pg chart | `infra/cloudnative-pg.yaml` | chart repo index |
| external-secrets chart | `infra/external-secrets.yaml` | chart repo index |
| garage-operator chart | `infra/garage-operator.yaml` | OCI registry tags |
| valkey chart ×2 | `platform/valkey/{cache,broker}.yaml` | chart repo index |
| Docs chart tag | `clusters/prod/sources.yaml` | `suitenumerique/docs` git tags |
| Docs image tags ×3 | `apps/docs/release.yaml` | the same git tag |
| Drive chart tag | `clusters/prod/sources.yaml` | `suitenumerique/drive` git tags |
| Drive image tags ×2 | `apps/drive/release.yaml` | the same git tag |
| collabora-online chart | `apps/collabora/release.yaml` | chart repo index |

Two git-tag pins now live in `clusters/prod/sources.yaml`, so both patterns are **anchored
to the repository URL**. An unanchored `ref: {tag: vX.Y.Z}` matches both and rewrites
Drive's tag to a Docs version — that is a real bug that was caught, not a hypothetical.

Collabora's chart bump does **not** move its image tag: `apps/collabora/release.yaml` pins
`image.tag` explicitly so a chart bump cannot move the application by itself. Check the new
chart's `appVersion` and update the tag in the same PR.

## Adding a chart

Three lines in `values.yaml`. `updatecli.d/helm-charts.yaml` is a template over that table,
so a new chart needs no new manifest:

```yaml
  - id: my-thing
    repo: https://example.org/charts
    chart: my-thing
    files: [infra/my-thing.yaml]
```

`files` is a list because one chart can be pinned in several places — Valkey is installed
twice, and both instances have to move together or the two releases drift.

An app that is *not* a chart version (La Suite publishes no Helm repository — adr/0104)
gets its own manifest, like `docs.yaml`. Copy that one; the shape is a single source
feeding every place the version appears, so a partial bump is not expressible.

## Three decisions worth knowing

**No `scms:` or `actions:` blocks.** updatecli edits the working tree and stops; the
workflow does the branch, commit and PR once for the whole run. mijn-bureau-infra repeats a
22-line GitHub SCM + pull-request block in each of its 21 manifests — roughly 460 lines
whose only content is naming the same repository again. It also means these manifests run
locally with no token and no remote.

**`kind: file`, not `kind: yaml`.** Every YAML engine updatecli offers re-serialises the
whole document on write. Measured on this repo: blank lines removed, aligned trailing
comments collapsed to one space, wrapped flow sequences re-flowed onto one line — 11 to 20
lines of unrelated churn per file, enough to bury the one line that actually changed. Text
replacement anchored on `chart: <name>` is byte-exact. Verified: a full behind-version
simulation restores every pin and leaves the tree byte-identical to where it started.

The anchor is also a safety property. `clusters/prod/sources.yaml` holds seven documents,
and updatecli's yamlpath engine writes to *every* document whose path matches — which
there would rewrite `platform-deps` and `platform-app`, our own charts, to a Docs version.
There is no document selector. A pattern that cannot match them is the fix.

**Autodiscovery is not used.** `crawlers: {flux: {}}` finds two of the six pins on this
layout, and one of the two is `office/config` — our own release pointer, which `release.sh`
owns and a bot must never touch. Explicit manifests cost a few lines and cannot surprise us.

## Deliberately not covered

**Keycloak.** Its version is not a string anywhere; it is five vendored manifest files that
are byte-identical copies of a GitHub tag (`platform/identity/operator/`). Upgrading means
re-downloading all five and diffing them. A bot that bumped a version string while leaving
those files at the old release would produce a repository that lies about what it runs, so
this pin stays manual — see the header of `platform/identity/operator/kustomization.yaml`.

**Our own artifacts.** `platform-deps`, `platform-app` and `office-config` are released by
`platform/scripts/publish.sh` and `release.sh`. They are pins, but they are ours.

## A bump is not live when it merges

Merging changes the pins; the cluster reads a published artifact. After merge, run
`./release.sh <next version>` and confirm all three layers report the new revision.
