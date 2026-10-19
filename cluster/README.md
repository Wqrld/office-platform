# cluster/

What the platform installs when the cluster does not already have it (adr/0112): Envoy
Gateway and MetalLB, chosen by `cluster.*.install`. Each is two Flux layers — the chart,
then `config/` with the objects that need its CRDs. `monitoring/` is the Prometheus stack
under `monitoring.mode: platform`; its second layer is the top-level `monitoring/`, which
`external` also uses (adr/0119). cert-manager is `infra/cert-manager`,
one layer later, because the Garage operator waits for it.
