# Find

Cross-app full-text search (Django + OpenSearch, BM25). Today it has exactly one consumer,
Docs, and one index prefix, `find-*`.

## The one departure from adr/0104

0104 says prod pins a **release tag**. `suitenumerique/find` has never cut one — zero git
tags, zero releases, and a single floating `main` tag on Docker Hub. So `release.yaml` pins a
**commit**, and the image by digest. This is a narrow exception, not a new default.

It also raises the stakes on 0104's compensating controls: with no version signal at all,
`tests/render-diff.sh` on bump and `tests/binding.py` are the only things between an upstream
force-push and a broken release. The two pins correspond today; nothing enforces that they
keep corresponding.

## Two asymmetric auth paths

Worth knowing before changing anything here — the tenant boundary is the index name, never a
request parameter.

| Path | Authenticates with | Target resolved from |
|---|---|---|
| `POST /documents/index/` | the shared service token, in the `find_service` table | `request.auth.index_name` — a service cannot write another's index |
| `POST /documents/search/` | the **end user's** OIDC access token, forwarded by Docs | `Service.objects.get(client_id=<introspected audience>)` |

Consequences that decide the config:

- The token is a plaintext column with `CheckConstraint(token__length=50)`. A 40-character
  password fails registration, which is why `office-token-50` exists.
- `client_id` must be `docs`, matching the Keycloak client id. A mismatch indexes fine and
  400s on search — and Docs swallows that into a title-search fallback, so it looks like
  "search works, badly" rather than an error.
- `OIDC_OP_URL` must equal Keycloak's `iss` byte for byte. Confirm with:
  `curl -s https://id.$BASE_DOMAIN/realms/office/.well-known/openid-configuration | jq -r .issuer`

We deliberately do **not** copy the reference deployment's
`for svc in services: svc.services.set(services)`, which grants every service cross-search
over every other. `get_opensearch_indices` already adds the caller's own name
unconditionally, so the `services` M2M stays empty.

## Gotchas paid for once

- **The migrate Job is immutable.** It is named `find-backend-migrate-<chartVersion>`, which
  never moves, and a Job's `spec.template` cannot be patched — so every env change fails the
  upgrade with `field is immutable` unless `migrateJobAnnotations` makes it a Helm hook with
  `before-hook-creation`.
- **The chart's default image does not exist.** `lasuite/find-backend` 404s on Docker Hub;
  the published image is `lasuite/find`. Overridden in `release.yaml`.
- **Find must be reached over its public URL.** See the header of `surround.yaml`.
- **The chart has no `envFrom`**, so every variable is an explicit `secretKeyRef`.
- **Its OpenSearch role needs `cluster_composite_ops`**, which every tenant role carries
  (`charts/platform-tenants`): the bulk indexing path uses it, and without it
  `manage.py index` fails on the first batch. The index grant stays `find-*` and nothing
  else.
- **Its OIDC client is a resource server**: it only introspects tokens other clients
  issued, authenticating to the introspection endpoint with its secret alone, so it needs
  no grant. Its client id, `find`, is also the audience Docs' tokens carry for it.

## Bringing it up

Find must exist before Docs' flag Job and reindex run — `docs: {requires: [find]}` in the
control plane's app table makes `app-docs` wait for `app-find`. Its realm client
and OpenSearch user are the tenants chart's (`oidc` and `search` in
`charts/control-plane/apps.yaml`), applied by its reconcile Jobs.

## Known limitations, recorded not fixed

- REST TLS to OpenSearch is **unverified** — `verify_certs=False` is hardcoded and there is
  no CA setting. Encryption yes, server authentication no. See `adr/0111`.
- `visited` is client-supplied and trusted. Docs computes it honestly from `LinkTrace`, but a
  token holder could enumerate non-restricted documents.
- **No throttling at all** — Find sets no `DEFAULT_THROTTLE_CLASSES`. Docs throttles its own
  API; Find does not.
- The `groups` ACL field is mapped, filtered on, and never populated (`views.py` hardcodes
  `groups = []`). Team-based access does not work; only per-user `sub` matching does.
