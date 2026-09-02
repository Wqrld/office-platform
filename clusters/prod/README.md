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
