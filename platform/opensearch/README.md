# Shared OpenSearch

One single-node instance in `office-data`, serving Find's `find-*` and Messages' indices. The security
posture — plugin on, TLS on the REST layer, per-app internal user scoped to an index prefix
— is recorded in `docs/adr/0111`.

## What isolates one app from another

The **index pattern**, not a request parameter. Each app's `search` entry in
`charts/platform-tenants/values.yaml` becomes an internal user whose role grants
`indices_all` on exactly those patterns — `find-*` for Find, `messages` for Messages — so an
app reaching for another's index gets a 403 from the server rather than a filtered result.
`platform-deps`' `opensearch` kind emits the same prefix into the app's environment.

There is no `admin` internal user. Cluster administration is the admin **certificate** only,
so there is no all-access password anywhere to leak.

## Changing the security config

`allow_default_init_securityindex: true` seeds `.opendistro_security` from the mounted files
**on first boot only**; after that the index is the source of truth and the files are
ignored. So the platform keeps the index in step itself: the tenants chart renders
`opensearch-security` — every file but the users' hashes, mounted as the first-boot config —
and an `opensearch-security-<hash>` Job that hashes each app's generated password with the
server's own `hash.sh` and uploads the config with `securityadmin.sh`. The name is a hash of
what it applies, so a change is a new Job, which runs once.

**Adding a user is adding a `search` entry.** Nothing to run. Two things the Job does on
purpose, both paid for once by hand:

- It uploads one config type at a time (`securityadmin.sh -f <file> -t <type>`), only the
  six types the chart defines. `-cd <dir>` aborts on an optional file it does not find
  *after* writing the index but *before* telling the nodes, which left the change written
  and unloaded. Each `-f` upload reloads on success.
- It hashes at run time. bcrypt re-salts, so a hash rendered by ESO or Helm is a different
  (equally valid) value on every render.

Rotating an app's password: delete `opensearch-user-<app>` (ESO draws a new one), re-run the
Job, restart the app —

```sh
kubectl -n office-data delete job -l app.kubernetes.io/instance=tenants
flux reconcile helmrelease tenants -n office-data --force
```

The admin certificate (`certificate.yaml`) is what the Job authenticates with, and the only
way into the security config: there is no admin user.

Verified against an OpenSearch 3.8.0 container on the rendered files: first boot with no
users, the Job's upload, `find` confined to `find-*` and `messages` to `messages` (403 on
each other's), and a second run that changes nothing a client can see.

## Gotchas paid for once

- **PKCS8 or the node will not start.** cert-manager emits PKCS1 by default; the security
  plugin cannot parse it and dies on `Unable to read the private key`. Both leaf
  Certificates set `privateKey.encoding: PKCS8`.
- **`DISABLE_INSTALL_DEMO_CONFIG: "true"` is required.** Without it the image installs demo
  certificates over ours, and separately refuses to start unless
  `OPENSEARCH_INITIAL_ADMIN_PASSWORD` is set.
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
`docs/reindex-docs.yaml`.
