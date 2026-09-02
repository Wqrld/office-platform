# config

Flux-reconciled configuration for the office platform. Thin by design: the charts live in
the `platform` repo and arrive as versioned OCI artifacts.

```
clusters/prod/   Flux entrypoint — sources, vars, four ordered Kustomizations
infra/           operators (CNPG, ESO, …)
platform/        shared stateful layer — gateway, postgres, valkey, objectstore, keycloak
apps/            one file per application
```

Reconcile order: `10-crds` → `20-infra` → `30-platform` → `40-apps`.

Licence: EUPL-1.2.
