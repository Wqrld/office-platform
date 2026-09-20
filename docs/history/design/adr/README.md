# Architecture decision records

One decision per file, a few paragraphs each. Format: context, decision, consequences.
Status is `Accepted`, `Proposed`, or `Superseded by NNNN`.

ADRs record *why*. In eighteen months someone will propose adding a service mesh; the
difference between a two-hour discussion and a two-week detour is whether the reasoning was
written down.

| # | Decision | Status |
|---|---|---|
| [0001](0001-fresh-repository.md) | Rebuild in fresh repositories rather than refactor | Accepted |
| [0002](0002-helm-library-chart.md) | A Helm library chart is the unit of reuse | **Amended by 0012** |
| [0003](0003-flux-over-argocd.md) | Flux v2 for delivery | Accepted |
| [0004](0004-drop-bitnami.md) | Remove all Bitnami charts, images and the common library | Accepted |
| [0005](0005-secrets-generate-once.md) | Generate secrets once into the cluster; never derive at render time | Accepted |
| [0006](0006-gateway-api-in-app-oidc.md) | Gateway API only; authentication stays in-app | Accepted |
| [0007](0007-defer-crossplane-rabbitmq.md) | Defer Crossplane and RabbitMQ | Accepted |
| [0008](0008-tenancy.md) | Ship single-tenant; keep names tenant-qualified | Accepted |
| [0009](0009-object-storage.md) | Garage via garage-operator; external S3 a first-class mode | Accepted |
| [0010](0010-licence.md) | Stay EUPL-1.2 | Accepted |
| [0011](0011-matrix-web-client.md) | Matrix web client | **Proposed — decide at M8** |
| [0012](0012-upstream-lasuite-charts.md) | Consume upstream charts; build the surround | Accepted |
| [0013](0013-kyverno-invariants.md) | Platform invariants live in Kyverno, not chart templates | Accepted |
