# Calendars

## What runs

`calendars.${BASE_DOMAIN}` — shared calendars, meeting scheduling, and a CalDAV endpoint
real clients (Thunderbird, iOS, Evolution) can subscribe to. The usual three releases
(`apps/README.md`): `calendars-deps`, `calendars`, `calendars-platform`.

Four workloads and three install Jobs:

| Workload | Image (the fork's, see Pins) | Port | Notes |
|---|---|---|---|
| backend | `ghcr.io/wqrld/calendars-backend` | 8000 | Django, gunicorn |
| frontend | `ghcr.io/wqrld/calendars-frontend` | 8080 | Caddy serving a Vite SPA |
| caldav | `ghcr.io/wqrld/calendars-caldav` | 80 | SabreDAV under Apache/PHP |
| worker | the backend image | — | **Dramatiq, not Celery** |

Jobs: `calendars-backend-migrate`, `calendars-backend-createsuperuser`,
`calendars-caldav-initdb`, all Helm hooks (`release.yaml` says why). Everything else about
how the values are wired — `PG*` names, the two schemas, Dramatiq's three URLs and its
`KEYS`, the frontend capability, the gaufre, silent login — is commented on the value itself.

### CalDAV is never routed from outside

`surround.yaml` routes `/caldav` to **`calendars-backend`**, not to `calendars-caldav`.

Django's `CalDAVProxyView` (`core/api/viewsets_caldav.py`) authenticates the request and
translates ACLs before forwarding. SabreDAV behind it trusts an API key and has no notion of
our users at all. The `calendars-caldav` Service stays ClusterIP and is reached only through
`CALDAV_URL`. Routing straight to it would publish every calendar in the system to anyone
who can reach the hostname.

`/.well-known/caldav` is in the same route and is easy to lose: it is served at the URL
**root** by `calendars/urls.py`, not under `/api`, and it is the first thing every CalDAV
client probes. Without it, Thunderbird and iOS find nothing and report no useful error.

## Pins and forks

### Where the chart comes from

The chart is written in the application's own repo at `src/helm/calendars`, which is exactly
what `adr/0104` expects. It is **not in any upstream tag**, and the upstreaming PR is not
open yet. So, like Projects and Messages, it comes from the fork's git tag
(`wqrld-calendars` at `v0.2.2`, `source.yaml`) — the same
tag that publishes the images — and one pin moves both.

### Pins

The three image tags are stated in `release.yaml` (`apps/README.md`, Conventions) as
`0.2.2`, without a `v` (`type=semver,pattern={{version}}` publishes `v0.2.2` as
`…-backend:0.2.2`), and updatecli tracks the FORK's tags.

**`0.2.2` is upstream `main` at `570b5e0` plus the two commits of the chart PR**: a CI fix
(`35d4ce0`) and the chart (`8a9c25d`). The fork's `main` is exactly that branch.

**The registry is the fork's, and has to be.** The backend probes are both on
`/__heartbeat__/`, upstream's own endpoint (a database check, upstream #150). No upstream
release has it yet: `v0.2.0` predates it, so against an upstream image both probes 404 and
liveness restarts the pod in a loop. `0.2.1` and earlier served the probes through
`dockerflow`, added by the fork's first chart commit; the PR dropped it for upstream's
endpoint.

**The fork's images run non-root.** The CI fix passes `DOCKER_USER=1001:127` to the backend
build, as Docs does, so the backend image declares `USER 1001:127`. Upstream's CI builds
without it, so its backend image runs as root and the chart's own `runAsNonRoot: true`
cannot start it: a `CreateContainerConfigError` with no logs. The frontend image is
distroless `nonroot` upstream too. `runAsUser: 1001` on backend and frontend states the user
in values, so an upstream image starts too.

## Install order / first admin

**The certificate.** `calendars.${BASE_DOMAIN}` must be in the SAN list before the
hostname is used, or the Gateway serves the wrong certificate and every call — browser and
CalDAV client alike — fails the handshake. It is in the same commit for that reason.

Then, in order: reconcile the platform layer, confirm `calendars-db`,
`valkey-user-calendars` and `oidc-client-calendars` exist and the `realm-*` Job completed,
reconcile apps, and **watch `calendars-caldav-initdb` first** — it is the one Job that can fail on a
privilege this integration assumed rather than verified. No `requires`: it depends on no
other app.

**The createsuperuser Job runs `migrate` first.** Both Jobs are hooks in the same phase and
Helm orders same-weight hooks by name, so `…-createsuperuser` runs before `…-migrate` on a
fresh install; `migrate` is idempotent. The account's `organization` (a non-null FK, keyed
by email domain and created on first OIDC login for real users) is made by the Job, because
this account never logs in through OIDC.

Last: every switcher lists Calendars once `apps.calendars` is on — the list is the control
plane's (`apps/README.md`, The switcher), served fresh, so nothing to flush.

## Gotchas

- **The frontend keeps `NET_BIND_SERVICE` in its bounding set, temporarily.**
  `/usr/bin/caddy` carries the file capability `cap_net_bind_service=ep`, and with
  `drop: [ALL]` under no_new_privs the kernel refuses the exec: `exec /usr/bin/caddy:
  operation not permitted`, a CrashLoopBackOff with that one log line. Measured: dropping
  ALL reproduces it, adding this one capability back fixes it. It is never used (the server
  listens on :8080); Docs avoids the problem with `nginx-unprivileged`, which has no file
  caps. The image no longer ships the capability (chart change 8), so this can go.
- **Invitation and RSVP mail is sent by the Dramatiq worker**, which reads only the shared
  `backend.envFrom`/`envVars`, not `backend.django.*`; `calendars-smtp` is attached there.

### Single-tenant on purpose

`OIDC_USERINFO_ORGANIZATION_CLAIM` and `RESOURCE_EMAIL_DOMAIN` are both left empty. The
first puts every user in one organization derived from their email domain; the second
disables resource mailboxes. Both are correct for this platform, and organizations are hard
to introduce afterwards — if that ever changes, it is a decision to take before the user
table fills up, not after.

### Known gaps

- **`WORKER_CONCURRENCY` is a sizing decision nobody made upstream.** `worker.py` passes
  `--processes 4 --threads 1` unless it is set, and each process is a full Django. Four is
  the argparse default. Set to 2 at `medium`, 1 at `small`, 4 at `large`.
- **`DJANGO_CONFIGURATION` must stay in `backend.envVars`.** `worker.py` does
  `os.environ.setdefault("DJANGO_CONFIGURATION", "Development")`, and
  `backend.django.envVars` is *not* read by the worker deployment. Move that one line and the
  worker silently runs the Development configuration — DEBUG on, a different cache, no error.
- **The shared Valkey ACLs isolate nothing.** Every user carries `~* &* +@all -@dangerous
  +flushdb` — all keys, all databases. Calendars keeps sessions in the cache
  (`SESSION_ENGINE = cache`), so this puts a fourth application's session store where the
  other three can read it and any of them can `FLUSHDB` it. Adding Calendars does not create
  this; it is the fourth reason to fix it. Narrowing to `~calendar*` per app is one line per
  user in `platform/valkey/*.yaml`.
- **Silent login** is on (`FRONTEND_SILENT_LOGIN_ENABLED` in `release.yaml`, upstream v0.2.0+).
  It is the first fork tag to carry it; `0.1.1` ignored the setting.
- **Sizing is unmeasured.** The numbers in `release.yaml` and the overlays are starting
  points, not `measure.py` output. The three install Jobs inherit `backend.resources` and run
  alongside the workloads, so the install **peak** is roughly one extra backend over the
  steady state. Read the peak.

## Upstream PRs

**The chart PR is not open yet.** It is the fork's `main`: upstream `main` plus a CI fix and
the chart. When it lands and upstream cuts a release carrying both, the `wqrld-calendars`
GitRepository's url becomes `github.com/suitenumerique/calendars` at that tag, the three
image tags move, and the repositories go back to `suitenumerique`. Nothing else changes.

### Chart changes found while integrating

What became of each, as of `v0.2.2`:

1. **The worker's shutdown time.** `worker.py` gives running tasks 600s to finish, against
   the pod's default 30s grace period. **Fixed in the PR:**
   `backend.worker.terminationGracePeriodSeconds`, 600 by default.
2. **The three Job names carry no chart version**, so a values change can collide with a Job
   the TTL has not collected. **Left as in Docs**, so the chart stays a copy of Docs'; Find's
   version suffix is the better pattern for a later PR.
3. **`backend.migrateJobAnnotations` is applied to the createsuperuser Job too**, so the two
   cannot be ordered with hook weights. **Left as in Docs.** `release.yaml` runs `migrate`
   inside its own createsuperuser command (Install order).
4. **`values.yaml` documented `envFrom` entries as `- secret: {name: …}`**, inherited from
   Docs. **Fixed in the PR:** `secretRef`.
5. **`backend.createsuperuser.command` works upstream.** Calendars has its own
   `createsuperuser` command (`core/management/commands/createsuperuser.py`) that takes
   `--email` and `--password` and creates the organization. `release.yaml` keeps its own
   command, which also runs `migrate` first.
6. **The publish workflow did not pass `DOCKER_USER`**, so the backend image ran as root and
   the chart's `runAsNonRoot: true` could not start it. **Fixed in the PR** (Pins).
7. **The probes.** The fork's first chart commit added `dockerflow` for `/__heartbeat__` and
   `/__lbheartbeat__`. Upstream has since added its own `/__heartbeat__/` (#150), so the PR
   drops `dockerflow` and points both probes there.
8. **The file capability on `/usr/bin/caddy`.** Gone upstream: the frontend image is now
   distroless, with Caddy from the release tarball, which carries no file capability. The
   `NET_BIND_SERVICE` in `release.yaml` (Gotchas) is no longer needed and can go in a later
   change.
