# Shared OpenSearch

One single-node instance in `office-data`, serving Find's `find-*` indices. The security
posture — plugin on, TLS on the REST layer, per-app internal user scoped to an index prefix
— is recorded in `platform/docs/adr/0111`.

## What isolates one app from another

The **index prefix**, not a request parameter. `opensearch-security-config` grants the
`find` user `indices_all` on `find-*` and nothing else, so an app reaching for another's
index gets a 403 from the server rather than a filtered result. `platform-deps`' `opensearch`
kind emits the same prefix into the app's environment.

There is no `admin` internal user. Cluster administration is the admin **certificate** only,
so there is no all-access password anywhere to leak.

## Changing the security config

`allow_default_init_securityindex: true` seeds `.opendistro_security` from the mounted files
**on first boot only**. After that the index is the source of truth and the files are
ignored — so editing `secrets/opensearch-users.yaml` and reconciling changes nothing.

To apply a change, or after rotating the `find` password:

```sh
kubectl -n office-data exec opensearch-cluster-master-0 -- \
  plugins/opensearch-security/tools/securityadmin.sh \
    -cd config/opensearch-security \
    -icl -nhnv \
    -cacert config/certs/ca.crt \
    -cert config/admin-certs/tls.crt \
    -key config/admin-certs/tls.key
```

This is why `opensearch-admin` exists in `certificate.yaml` despite nothing mounting it in
steady state.

## Gotchas paid for once

- **PKCS8 or the node will not start.** cert-manager emits PKCS1 by default; the security
  plugin cannot parse it and dies on `Unable to read the private key`. Both leaf
  Certificates set `privateKey.encoding: PKCS8`.
- **`DISABLE_INSTALL_DEMO_CONFIG: "true"` is required.** Without it the image installs demo
  certificates over ours, and separately refuses to start unless
  `OPENSEARCH_INITIAL_ADMIN_PASSWORD` is set.
- **`bcrypt` re-salts on every render**, so `opensearch-security-config` is
  `refreshInterval: "0"`. A refreshing one would rewrite the Secret with a different but
  equally valid hash and roll the StatefulSet on every sync.
- **No `sysctlInit`.** It runs a privileged initContainer that this namespace's `baseline`
  PSA refuses, and the node is already at `vm.max_map_count=1048576`.
- **The chart's `resources` defaults are wrong for a JVM** — 1000m CPU and 100Mi memory
  against a 512M heap. Both are overridden.

## What TLS here does not buy

Find hardcodes `verify_certs=False` (`core/services/opensearch.py:41`) and exposes no CA
setting, so the REST connection is encrypted but the server is never authenticated. Fixing
that needs an upstream `OPENSEARCH_CA_CERTS` setting — see `adr/0111`.

## No index migration path

Mappings are `dynamic: strict` and `ensure_index_exists` is create-if-404 only: there is no
alias scheme and no reindex-in-place. A mapping change means deleting the index and re-running
`apps/docs/reindex.yaml`.
