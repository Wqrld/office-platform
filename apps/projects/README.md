# Projects

`projects.${BASE_DOMAIN}` — boards, lists and cards for project management, with live
collaboration. La Suite's Projects (`suitenumerique/projects`), a Planka fork: Sails on
Node, a React SPA served by the same process.

Three releases, the same shape as the others: `projects-deps` (platform-deps), `projects`
(the chart), `projects-platform` (platform-app).

One workload and no Jobs:

| Workload | Image | Port | Notes |
|---|---|---|---|
| backend | `ghcr.io/wqrld/projects` (the fork, see Pins) | 1337 | SPA, API, socket.io, files |

`start.sh` runs `db/init.js` — knex migrations under knex's own lock — on every start, then
the server. Two replicas starting at once is therefore safe; a migration that fails is a
pod that does not start, not a Job that failed quietly.

## Its own spellings

Nothing Projects reads was spelled by an existing profile, so `env: projects` is a family
of its own (`charts/platform-deps/templates/_profiles.tpl`):

| Kind | Profile | Reads |
|---|---|---|
| postgres | `url` | `DATABASE_URL`, assembled in the ExternalSecret |
| cache | `django` | `REDIS_URL` — the same name, so the existing profile |
| objectstore | `s3` | `S3_*`, plus `S3_FORCE_PATH_STYLE` as a constant |
| smtp | `nodemailer` | `SMTP_*`; `SMTP_SECURE` is the relay's `useSSL` |
| oidc | `env: discovery` | `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SCOPES` |

**OIDC goes over the public issuer for everything.** openid-client discovers its endpoints
from `OIDC_ISSUER`, and discovery answers with public URLs, so the browser/back-channel split
the Django apps get (`_oidc.tpl`) cannot be expressed here. Hence `external: 443` in the
egress list and no `identity` rule.

## Files never leave through the bucket

Upstream links avatars and background images straight to the bucket
(`S3FileManager.buildUrl`); only attachments are streamed by the server. Against a private
Garage that is a broken image on every avatar, and a public bucket would publish the
attachments beside them — Garage has no per-prefix anonymous read.

The fork adds `S3_PROXY_PUBLIC_FILES`: the server streams those two prefixes too, at the
same URLs local storage uses (`/user-avatars/…`, `/project-background-images/…`). So there
is no media proxy, no `publicEndpoint`, and the bucket is as private as Drive's.

## Where the chart comes from, and when that changes

The chart is written in the application's repo at `src/helm/projects`, **copied from Docs'
`src/helm/impress`** and cut down to one workload, so an upstream reviewer reads a chart
they already maintain. It is not in any upstream tag, so it comes from the fork's own git
tag (`GitRepository` `wqrld-projects` on `github.com/Wqrld/projects`,
`charts/control-plane/templates/sources.yaml`) — the same tag that publishes the image, so
chart and image move together.

**When the PR lands:** the `GitRepository`'s url becomes `github.com/suitenumerique/projects`
at the tag that carries the chart. Nothing else changes.

## Pins

The image is the fork's (`Wqrld/projects`), tagged without a `v` like upstream's CI does,
until upstream carries both patches below. updatecli tracks the fork's tags
(`updatecli/updatecli.d/projects.yaml`); when upstream releases them, the repository goes
back to `docker.io/lasuite/projects`.

## Upstream changes (the PR)

1. **The chart**, `src/helm/projects`. One deliberate divergence from Docs': the `envFrom`
   example says `secretRef:`, not `secret:` — the latter is not an `EnvFromSource`, and
   Kubernetes 1.34 rejects it (Calendars' README, chart change 4).
2. **`S3_PROXY_PUBLIC_FILES`** — above. Rejects `.`/`..` segments before a key reaches the
   SDK, which would otherwise normalise `/user-avatars/../../private/…` into an attachment.
3. **`USER 1000:1000`** in the Dockerfile. `USER node` is a name, and the kubelet cannot
   verify a name against `runAsNonRoot`, so the chart's own securityContext cannot start
   the published image. `release.yaml` sets `runAsUser: 1000` until then.

## Known gaps

- **Logout is one-way.** Projects has no back- or front-channel logout endpoint: logging out
  here ends the Keycloak session, logging out elsewhere leaves this one alive until its
  token expires (`TOKEN_EXPIRES_IN`, 365 days by default).
- **No admin through SSO.** `OIDC_IGNORE_ROLES` is on because no realm role maps to Projects'
  admin; the first admin is set by hand (below). A realm group and `OIDC_ADMIN_ROLES` would
  make it declarative.
- **The shared Valkey ACLs isolate nothing** — the same `~* &*` line every app has
  (Calendars' README). Projects keeps sessions there.
- **Sizing is unmeasured.** Starting points; image resizing on upload is the memory spike.

## Install order

The same two things that do not take effect by reconciling as for every login client:

1. **The realm import is import-once.** Run `platform/identity/add-client.sh projects` once
   `oidc-client-projects` exists.
2. **The certificate.** `projects.${BASE_DOMAIN}` comes from `charts/control-plane/apps.yaml`;
   let the certificate reissue before the hostname is used.

Then: reconcile the platform layer, confirm `projects-db`, `valkey-user-projects` and
`oidc-client-projects` exist, run `add-client.sh`, reconcile apps, and watch the first pod's
log for the migrations. Log in once through Keycloak, then make that user admin:

```sh
kubectl -n office-data exec -it office-pg-1 -- psql projects \
  -c "update user_account set is_admin = true where email = '<you>'"
```

(check the column against `server/db/migrations` of the running version first).
