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

## Checks

Every job in `.github/workflows/pr.yaml` runs one of these, so the check that fails in CI is
the check you can run here:

| Command | Question it answers |
|---|---|
| `./tests/build.sh [dir]` | does every layer of every cluster build, with no `${VAR}` left unresolved? |
| `./tests/render-diff.sh [base]` | what does this change do to what the clusters actually apply? |
| `./tests/binding.py [app]` | does our surround still attach to what the upstream charts create? |
| `./tests/profiles.py [size]` | do the size profiles still say what they claim to say? |
| `./tests/kubeconform.sh [dir]` | is what Flux would apply valid for the API server? |
| `conftest verify --policy policy` | do the static rules still fire, both directions? |
| `conftest test --policy policy --parser yaml --all-namespaces apps/ platform/ clusters/ infra/` | are the pins and remediation settings still as decided? |

`binding.py` and `profiles.py` render our own charts from `../platform/charts`, so they need
the charts repo checked out beside this one, and they fetch the pinned upstream charts, so
they need network. Everything else is offline.

Nothing here needs a cluster. What does — bootstrap-from-scratch, the upgrade test, the auth
smoke test, external-mode rotation — is nightly, and is not written yet.

Licence: EUPL-1.2.
