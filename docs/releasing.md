# Releasing

One number for the config artifact and the four charts; a cluster runs it by naming it.

```sh
./release.sh 2.1.0                  # from a clean tree, to the registry in release.sh
git commit -am 'release 2.1.0'      # the Chart.yaml bumps it leaves behind
```

Versions are immutable: `release.sh` refuses a number that exists, so a rollback can never
rewrite what it rolls back to. A dirty tree is refused too — an artifact must be traceable
to a commit. Registry and credentials: `REGISTRY` in `release.sh`, `~/.harbor-robot`
(line 1 user, line 2 password; `HARBOR_ROBOT_FILE` overrides).

Then, per cluster, `ref: {tag: "2.1.0"}` in its `cluster.yaml`. For ours that is
`../office-clusters/<cluster>/cluster.yaml` and `../office-clusters/push.sh`, which
publishes that repository as the artifact both clusters sync; it lands within 5m, or now:

```sh
flux -n flux-system reconcile source oci flux-system && flux get hr -n flux-system
```

Demo first. Rolling back is editing the tag back. Before a release that adds a required
value, both cluster files carry it first — a refused HelmRelease is a message, but a
default that takes over a hand-made object is not (`smtp.configured`, see `install.md`).
