# cluster/

What the platform installs when the cluster does not already have it (adr/0112): Envoy
Gateway and MetalLB, chosen by `cluster.*.install`. Each is two Flux layers — the chart,
then `config/` with the objects that need its CRDs. cert-manager is `infra/cert-manager`,
one layer later, because the Garage operator waits for it.
