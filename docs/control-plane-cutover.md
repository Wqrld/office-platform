# Runbook — moving a cluster onto the control-plane chart

For a cluster that was bootstrapped from `clusters/<env>/` (config ≤ 1.7.x): its Flux
still syncs `clusters/prod` from `office/config:latest` and runs `20-infra`,
`30-platform` and `40-apps`. This moves it onto `clusters/<env>/cluster.yaml` and the
control-plane chart **without recreating a single workload**. A fresh cluster never needs
this — `bootstrap.md` already ends on the chart.

**Why it is not one `kubectl apply`.** Two things would otherwise destroy or duplicate
state:

1. *Pruning.* Every object on the cluster is in the inventory of `20-infra`, `30-platform`
   or `40-apps`, all `prune: true`. Deleting a pruning Kustomization garbage-collects its
   inventory — the whole platform. They are switched to `prune: false` first, so being
   pruned themselves leaves their objects standing for the new Kustomizations to adopt.
2. *Name collisions.* The chart renders `cluster-vars`, every chart source and
   `office-config` under the names the old files used, because every HelmRelease in `apps/`
   points at those names. Helm refuses to install over an object it does not own, so the
   existing ones are marked for adoption instead — the same two-phase handover that moved
   Docs onto the platform charts (PROGRESS.md).

The new Kustomizations adopt everything else by server-side apply: the objects' Flux
ownership labels change from `40-apps` to `app-docs`, nothing is deleted or recreated.
Check the UIDs before and after; that is the whole verification.

## Before

- **2.0.0** published with `./release.sh 2.0.0` — the config artifact and all four charts,
  the first version cut from this layout (`platform-deps` learned `objectstore.mode` in
  it). Nothing on the cluster moves yet: it still reads config 1.7.x and charts 0.2.10.
- `../office-clusters/` pushed (`./push.sh`), so `office/clusters:latest` exists with `prod/` in it.
- `tests/clusters/prod.yaml` and `../office-clusters/prod/cluster.yaml` say the same thing.
  `./dns.py ../office-clusters/prod/cluster.yaml --check` is clean.

## Cutover

```sh
# 0. Snapshot what must not change.
kubectl get ns,hr,cluster,keycloak,garagecluster,gatewayclass,gateway -A -o custom-columns=KIND:.kind,NS:.metadata.namespace,NAME:.metadata.name,UID:.metadata.uid > /tmp/before.txt

# 1. Freeze the old control plane so a :latest reconcile cannot undo the next step.
flux -n flux-system suspend kustomization flux-system

# 2. Nothing may be pruned by the handover.
kubectl -n flux-system patch kustomization 20-infra 30-platform 40-apps \
  --type=merge -p '{"spec":{"prune":false}}'

# 3. The objects the chart renders under the same names: keep them, and let Helm adopt them.
kept="configmap/cluster-vars ocirepository/office-config ocirepository/platform-deps ocirepository/platform-app
      helmrepository/cloudnative-pg helmrepository/external-secrets helmrepository/valkey helmrepository/opensearch
      helmrepository/collabora helmrepository/calendars helmrepository/garage-operator
      gitrepository/suitenumerique-docs gitrepository/suitenumerique-drive gitrepository/suitenumerique-find
      gitrepository/suitenumerique-meet gitrepository/livekit-helm"
kubectl -n flux-system annotate $kept --overwrite \
  kustomize.toolkit.fluxcd.io/prune=disabled \
  meta.helm.sh/release-name=platform meta.helm.sh/release-namespace=flux-system
kubectl -n flux-system label $kept --overwrite app.kubernetes.io/managed-by=Helm

# 4. The switch: the FluxInstance now syncs the organisation's file, which carries the
#    chart pin and the values. flux-operator rewrites the flux-system source and
#    Kustomization in place; resume in case it kept the suspension.
kubectl apply -f ../office-clusters/prod/cluster.yaml
flux -n flux-system resume kustomization flux-system
flux -n flux-system reconcile source oci flux-system

# 5. Watch it land. The HelmRelease installs the control plane; the old layer
#    Kustomizations are pruned by flux-system (their objects stay, step 2); the new ones
#    adopt everything and report Ready without applying a change.
flux get hr -n flux-system                 # platform: Ready, chart 2.0.0
flux get kustomizations -A --watch         # infra, platform, objectstore, app-* Ready; 20-/30-/40- gone
```

## After

```sh
kubectl get ns,hr,cluster,keycloak,garagecluster,gatewayclass,gateway -A -o custom-columns=KIND:.kind,NS:.metadata.namespace,NAME:.metadata.name,UID:.metadata.uid > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt        # empty: every object kept its UID
kubectl get hr -A                          # no HelmRelease reinstalled — same revisions
kubectl -n flux-system get kustomization 20-infra 30-platform 40-apps   # NotFound
```

Then `demo`, identically, with `../office-clusters/demo/cluster.yaml` — it is where the next
version goes first from now on.

## If it goes wrong

Before step 4 nothing has changed but some annotations and a suspension:
`flux resume kustomization flux-system` puts it back. After step 4 the old control plane
is still in `office/config:latest` — `release.sh` no longer pushes that tag, so it stays
at the last old-style release — and the old FluxInstance is in git history:

```sh
# The same two hazards, mirrored: uninstalling the chart deletes its Kustomizations, and a
# deleted pruning Kustomization takes its inventory with it — so prune off first — and Helm
# deletes what it adopted unless told to keep it.
kubectl -n flux-system get kustomization -o name | grep -v /flux-system \
  | xargs kubectl -n flux-system patch --type=merge -p '{"spec":{"prune":false}}'
kubectl -n flux-system annotate $kept --overwrite helm.sh/resource-policy=keep
git show 6b7af2f:clusters/prod/flux-instance.yaml | kubectl apply -f -
```

The old `flux-system` Kustomization then prunes the HelmRelease (its Kustomizations go,
their objects stay), and the old layer Kustomizations come back at `prune: true` and adopt
their objects again. A bad *value* never gets this far: it is a HelmRelease that refuses
with a message, which `tests/control_plane.py` catches on the values file first.
