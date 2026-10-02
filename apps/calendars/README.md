# Calendars

`calendars.${BASE_DOMAIN}` — shared calendars, meeting scheduling, and a CalDAV endpoint
real clients (Thunderbird, iOS, Evolution) can subscribe to.

Three releases, the same shape as Docs, Drive and Find: `calendars-deps` (platform-deps),
`calendars` (the upstream chart), `calendars-platform` (platform-app).

Four workloads and three install Jobs:

| Workload | Image | Port | Notes |
|---|---|---|---|
| backend | `ghcr.io/suitenumerique/calendars-backend` | 8000 | Django, gunicorn |
| frontend | `ghcr.io/suitenumerique/calendars-frontend` | 8080 | Caddy serving a Vite SPA |
| caldav | `ghcr.io/suitenumerique/calendars-caldav` | 80 | SabreDAV under Apache/PHP |
| worker | the backend image | — | **Dramatiq, not Celery** |

Jobs: `calendars-backend-migrate`, `calendars-backend-createsuperuser`,
`calendars-caldav-initdb`, all Helm hooks (`release.yaml` says why). Everything else about
how the values are wired — `PG*` names, the two schemas, Dramatiq's three URLs and its
`KEYS`, the frontend capability, the gaufre, silent login — is commented on the value itself.

## Where the chart comes from, and when that changes

The chart is written in the application's own repo at `src/helm/calendars`, which is exactly
what `adr/0104` expects. It is **not in any upstream tag**: `v0.1.0` predates it and the
upstreaming PR is open. So, like Projects and Messages, it comes from the fork's git tag —
the same tag that publishes the images — and one pin moves both.

**When the PR lands:** the `wqrld-calendars` GitRepository's url becomes
`github.com/suitenumerique/calendars` at the tag that carries the chart. Nothing else changes.

## Pins

The chart declares `appVersion: latest`, so the three image tags are stated in `release.yaml`,
without a `v` (`v0.1.1` publishes `…-backend:0.1.1`), and updatecli tracks the FORK's tags:
upstream's newest, `v0.1.0`, predates the health endpoints the chart's probes need.

## CalDAV is never routed from outside

`surround.yaml` routes `/caldav` to **`calendars-backend`**, not to `calendars-caldav`.

Django's `CalDAVProxyView` (`core/api/viewsets_caldav.py`) authenticates the request and
translates ACLs before forwarding. SabreDAV behind it trusts an API key and has no notion of
our users at all. The `calendars-caldav` Service stays ClusterIP and is reached only through
`CALDAV_URL`. Routing straight to it would publish every calendar in the system to anyone
who can reach the hostname.

`/.well-known/caldav` is in the same route and is easy to lose: it is served at the URL
**root** by `calendars/urls.py`, not under `/api`, and it is the first thing every CalDAV
client probes. Without it, Thunderbird and iOS find nothing and report no useful error.

## Single-tenant on purpose

`OIDC_USERINFO_ORGANIZATION_CLAIM` and `RESOURCE_EMAIL_DOMAIN` are both left empty. The
first puts every user in one organization derived from their email domain; the second
disables resource mailboxes. Both are correct for this platform, and organizations are hard
to introduce afterwards — if that ever changes, it is a decision to take before the user
table fills up, not after.

## Known gaps

- **The worker's shutdown timeout is a lie.** `worker.py` asks dramatiq for
  `--worker-shutdown-timeout 600000` (10 minutes) while the pod's default
  `terminationGracePeriodSeconds` is 30, and the chart exposes no way to raise it. A rolling
  update SIGKILLs a worker mid-task. One field upstream fixes it; there is no workaround in
  values. Listed under "chart changes" below.
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
- **Silent login is off, and cannot be turned on from values.** An anonymous visitor with a
  live Keycloak session still sees the home page and a login button. It needs three changes in
  the application itself (`release.yaml`, the OIDC block).
- **Sizing is unmeasured.** The numbers in `release.yaml` and the overlays are starting
  points, not `measure.py` output. The three install Jobs inherit `backend.resources` and run
  alongside the workloads, so the install **peak** is roughly one extra backend over the
  steady state. Read the peak.

## Chart changes to make before the upstream PR

All found while integrating; none blocks deployment except by workaround.

1. **`terminationGracePeriodSeconds` is not exposed** on any of the four Deployments, and the
   worker asks for a 600s shutdown timeout against a 30s default.
2. **The three Job names carry no chart version**, so a values change can collide with a Job
   the TTL has not collected. Docs has the same shape; Find's version suffix is the better
   pattern.
3. **`backend.migrateJobAnnotations` is applied to the createsuperuser Job too**, so the two
   cannot be ordered relative to each other with hook weights. Either a separate
   `createsuperuserJobAnnotations`, or a default weight that puts migrate first.
4. **`values.yaml` documents `envFrom` entries as `- secret: {name: …}`**, inherited from
   Docs. That is not an `EnvFromSource`; the chart passes the list through `toYaml` and
   Kubernetes 1.34 rejects it with `unknown field "envFrom[0].secret"`. The correct key is
   `secretRef`.
5. **`backend.createsuperuser.command` cannot work as shipped**: `manage.py createsuperuser`
   has no `--password` flag, `USERNAME_FIELD` is `admin_email` rather than `email`, and
   `organization` is a non-null FK the command never sets.
6. **The release workflow dropped Docs' `docker_user` input**, so every published image ran
   as root and the chart's own `runAsNonRoot: true` could not start it; the frontend's
   `FROM caddy:2-alpine` stage additionally had no `USER` line. **Already fixed in the fork**
   (`v0.1.1`) and verified — this one is ready to send upstream as-is. It is the one that
   actually blocks a clean install, and it fails as a `CreateContainerConfigError` with no
   logs.
7. **`HELM_PLAN.md`'s open probe question is answerable and should be closed in the chart's
   README.** It says `/__heartbeat__` and `/__lbheartbeat__` "appear only in
   `SECURE_REDIRECT_EXEMPT` and no view backs them". `dockerflow.django.middleware.
   DockerflowMiddleware` is in `MIDDLEWARE` and serves both paths itself, before the URL
   resolver — no `urls` include is needed. The chart's default probe block is correct as
   shipped and needs no override here.
8. **The frontend image ships a binary the chart's own securityContext cannot execute.**
   `caddy:2-alpine` sets `cap_net_bind_service=ep` on `/usr/bin/caddy`; the chart drops all
   capabilities and forbids privilege escalation, so the exec fails with `operation not
   permitted`. `setcap -r /usr/bin/caddy` in the `frontend-production` stage fixes it with
   no capability grant anywhere — verified serving with ALL dropped. The server binds :8080
   and never needed the capability.

## Install order

The platform layer has two things that do **not** take effect by reconciling:

1. **The realm import is import-once.** Adding the `calendars` client to
   `platform/identity/realm.yaml` creates nothing on a realm that is already imported. Run
   `platform/identity/add-client.sh calendars` once the `oidc-client-calendars` Secret exists.
2. **The certificate.** `calendars.${BASE_DOMAIN}` must be in the SAN list before the
   hostname is used, or the Gateway serves the wrong certificate and every call — browser and
   CalDAV client alike — fails the handshake. It is in the same commit for that reason.

Then, in order: reconcile the platform layer, confirm `calendars-db`,
`valkey-user-calendars` and `oidc-client-calendars` exist, run `add-client.sh`, reconcile
apps, and **watch `calendars-caldav-initdb` first** — it is the one Job that can fail on a
privilege this integration assumed rather than verified.

Last: every switcher lists Calendars once `apps.calendars` is on — the list is the control
plane's (`apps/README.md`, The switcher), served fresh, so nothing to flush.
