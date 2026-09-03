# clusters/prod

Flux entrypoint. `FluxInstance` syncs this directory; everything else follows from it.

```
20-infra     operators — CNPG, External Secrets
30-platform  shared stateful layer — gateway, postgres, cache, object store, identity
40-apps      applications
```

Each layer `dependsOn` the previous and waits for health, so ordering is declared rather
than assumed.

**There is deliberately no `10-crds` layer yet.** The design set reserves it because Helm
does not upgrade CRDs, and the silent failure is a new field being ignored. Today every CRD
we rely on is either pre-existing in the cluster (Gateway API, cert-manager,
`monitoring.coreos.com`) or installed by an operator chart on first install. The slot and
the number are kept free; the layer arrives the first time a CRD upgrade actually needs
managing separately, rather than existing empty.

Scalars come from `vars.yaml` via `postBuild.substituteFrom`.

## Two tags, and why

`office/config` carries a moving `:latest` and immutable `:X.Y.Z` version tags.

| | read from | moves when |
|---|---|---|
| `clusters/prod` (this dir) | `:latest`, via `FluxInstance.spec.sync` | any push |
| `infra/`, `platform/`, `apps/` | `:X.Y.Z`, via `OCIRepository/office-config` | the tag in `config-source.yaml` is edited |

So production advances only by editing a version number. A stray `flux push` to `:latest`
changes the layer definitions and the pointer — it cannot move the workloads.

The `FluxInstance` itself deliberately stays on `:latest`. It cannot be pinned: it lives
inside the path it syncs, so the pointer to a new version would only exist inside a version
Flux is not yet pulling, and it could never learn that version exists. Putting the pointer
in a separate object breaks the cycle.

## Releasing and rolling back

Both are `./release.sh <version>` from `config/`:

```
./release.sh 1.1.0     # publish :1.1.0, point at it, push :latest
./release.sh 1.0.0     # roll back — repoints and pushes :latest only
```

The script never re-pushes a version tag that already exists, so published versions stay
immutable and a rollback cannot rewrite its own target. The artifact revision records the
git SHA, and a dirty tree is marked `-dirty` in it — check for that warning, because a
version that does not name a commit is a version you cannot reason about later.

Releasing leaves one uncommitted change behind: the pointer this script just rewrote.
Commit it. The SHA recorded in the artifact is read *before* that rewrite, so a version's
recorded commit is the one it was built from, not the one that bumps the pointer to it:

```
$ crane manifest .../config:1.2.1 | jq -r '.annotations["org.opencontainers.image.revision"]'
1.2.1@sha1:9e60594          # the commit whose tree was published
```

For an emergency rollback without a push:

```
kubectl -n flux-system patch ocirepository office-config --type=merge \
  -p '{"spec":{"ref":{"tag":"1.0.0"}}}'
```

That drifts from the artifact and the next `:latest` reconcile reverts it — follow up with
a real `./release.sh 1.0.0`.
