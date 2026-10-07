# Releasing

A release is a git tag, `v<version>`, on a commit whose four charts carry that version. A
cluster runs it by naming the tag; the control plane reads the config and the platform
charts from the same tag (adr/0114).

```sh
./release.sh 2.3.0                  # from a clean tree: bumps, commits, tags
git push origin HEAD v2.3.0         # pushing the tag is the release
```

`release.sh` sets `version` and `appVersion` in all four charts and the tag in
`examples/cluster.yaml`, turns `## Unreleased` in `CHANGELOG.md` into the version's
section, commits `🔖 (release) <version>` and tags it. It refuses a dirty tree and a tag that exists locally or on `origin`. On the
push, `.github/workflows/release.yaml` checks the tag against the charts and creates the
GitHub release from the CHANGELOG section.

Versions are immutable: a rollback must never rewrite what it rolls back to. `release.sh`
will not reuse a tag; a tag protection rule on `v*` in the GitHub repository settings keeps
a pushed one from being moved or deleted.

Then, per cluster, `ref: {tag: v2.3.0}` on the `platform` GitRepository in its
`cluster.yaml`. If the cluster syncs that file from a source (`sync` in
`examples/cluster.yaml`), publish it there; it lands within 30m, or now:

```sh
flux -n flux-system reconcile source git platform && flux get hr -n flux-system
```

A test cluster first. Rolling back is editing the tag back. Before a release that adds a
required value, every cluster file carries it first — a refused HelmRelease is a message,
but a default that takes over a hand-made object is not (`smtp.configured`, see
`install.md`).
