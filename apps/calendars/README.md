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
`calendars-caldav-initdb`. All three are Helm hooks — see "Why the Jobs are hooks" below.

## Where the chart comes from, and when that changes

The chart is written in the application's own repo at `src/helm/calendars`, which is exactly
what `adr/0104` expects. It is **not in any upstream tag**: `v0.1.0` predates it and the
upstreaming PR is open. So it is packaged and served from our own Helm repository
(`https://gh.haaijer.dev`, `clusters/prod/sources.yaml`) and consumed as an ordinary
versioned chart.

The alternatives were worse. Pinning `suitenumerique/calendars` at `main` is denied by
`policy/pins.rego`, correctly. Pinning a commit is Find's exception and should stay an
exception of one. Vendoring the chart into `helm-charts/charts` means maintaining it in two
places for the length of the review.

**When the PR lands:** the `HelmRepository` becomes a `GitRepository` on
`github.com/suitenumerique/calendars` at a tag with `ignore: !/src/helm`, and
`release.yaml`'s `chart.spec` becomes `chart: src/helm/calendars`. Nothing else changes.

## The chart version and the image tags are separate pins, and shaped differently

The chart declares `appVersion: latest`, so it pins nothing, and its three image defaults
are literally `latest`. All three tags are stated in `release.yaml`.

**The image tags carry no `v`.** `docker-publish.yml` uses `type=semver,pattern={{version}}`,
so the git tag `v0.1.1` publishes `…-backend:0.1.1`. Docs and Drive publish and are pinned
as `v5.5.0`. That is why `updatecli/updatecli.d/calendars.yaml` cannot reuse the shared
pattern: it strips the `v` in a source transformer and its target pattern is anchored on the
quoted, `v`-less form, which also keeps it away from Docs' and Drive's pins in other files.

**updatecli tracks the FORK's tags, not upstream's.** Pointing it at
`suitenumerique/calendars` would be a silent downgrade — upstream's newest tag is `v0.1.0`,
which predates the health endpoints the chart's probes need.

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

## `PG*`, not `DB_*`

`server.php` and `init-database.sh` read libpq's own variable names —
`PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` — while the backend reads the `django`
profile's `DB_*`. Same role, same database, two spellings.

There is deliberately **no `libpq` postgres profile** in `platform-lib` for this.
`platform-lib`'s own rule is "add a profile when a third app needs the same spelling; two is
a coincidence", and here there is exactly one consumer. The chart's `env.transformDict`
renders a map value as `valueFrom`, so five `secretKeyRef` lines in `release.yaml` reach into
the Secret the `django` profile already wrote, and no credential passes through Helm values.

## One database, two schemas

`init-database.sh` creates schema `sabre` in the application's own database and puts every
SabreDAV table there (`CALDAV_DB_SCHEMA`, set on both the caldav pod and its initdb Job).
Django keeps `public`. The role owns the database, so it can create the schema. There is no
second CNPG `Database` object.

**One thing to watch on the first install.** Before touching the target the script runs
`PGDATABASE=postgres psql -tAc "SELECT 1 FROM pg_database…"` and creates the database if it
is missing. CNPG has already created `calendars`, so nothing is created and the role needs no
`CREATEDB` — but it does need `CONNECT` on `postgres`, which `PUBLIC` grants by default on a
stock cluster. If that grant is ever revoked, `calendars-caldav-initdb` is what breaks, and
the fix is a one-line upstream patch to skip the probe when `PGDATABASE` already connects.

## Dramatiq needs three Redis URLs, and that is why `cache.dramatiq` exists

`REDIS_URL` (cache and sessions), `DRAMATIQ_BROKER_URL`, `DRAMATIQ_RESULT_BACKEND_URL`. The
third one carries a password, so it cannot be composed with `valueFrom` in the release — it
has to come out of the ExternalSecret template, which is what the new `cache.dramatiq`
profile in `platform-lib` is for.

**Results go on the cache instance, not the broker.** Dramatiq holds results for 30 days. On
the broker (`noeviction`, by design) a filled result set stops the queue; on the cache
(`allkeys-lru`) a lost result is a `/tasks/<id>/` poll that returns nothing. That is the
cheaper failure. Same instance as `cache`, so it is the same ACL user and one password draw;
only the `db` number differs, which keeps result payloads out of the session keys.

## Why the Jobs are hooks, and why createsuperuser runs `migrate`

All three Job names are stable — `calendars-backend-migrate`, `-createsuperuser`,
`calendars-caldav-initdb` carry no chart version — and a Job's `spec.template` is immutable.
The chart's `ttlSecondsAfterFinished: 30` usually collects them in time, but a values change
that lands inside that window fails the upgrade with `field is immutable`. So all three carry
`helm.sh/hook` + `hook-delete-policy: before-hook-creation`, which deletes the previous Job
first. `backend.migrateJobAnnotations` reaches migrate **and** createsuperuser;
`caldav.initdbJobAnnotations` reaches initdb.

That has one consequence worth knowing. Helm orders same-weight hooks **by name**, so
`calendars-backend-createsuperuser` runs *before* `calendars-backend-migrate` — on a fresh
install, before any table exists. The annotations are one values key shared by both Jobs, so
there is no per-Job weight to fix it with. The createsuperuser command therefore runs
`migrate --no-input` itself first; it is idempotent, so paying for it twice is cheaper than a
Job that only works in one order.

The command is replaced for two other reasons anyway: Django's `createsuperuser` has **no
`--password` flag**, and this model's `USERNAME_FIELD` is `admin_email`, not `email`. The
chart's default cannot work as shipped. The replacement is an idempotent ORM upsert, like
Docs'. It also creates the `Organization`: that FK is non-null, every user belongs to exactly
one org keyed by email domain (`resolve_organization`), and it is normally created on first
OIDC login — which this account never does.

## The images come from the fork too, not just the chart

This is the thing that is easiest to get wrong, and it fails in two different ways.

`release.yaml` pins `ghcr.io/wqrld/calendars-{backend,frontend,caldav}:0.1.1`. Not
`suitenumerique`, and the reason is not tidiness:

- **`dockerflow` postdates `v0.1.0`.** It is what serves `/__heartbeat__` and
  `/__lbheartbeat__` — `DockerflowMiddleware.process_request` matches both paths directly,
  so no `urls` include is needed and the chart's default probe block is correct as shipped.
  But the package was added in `51444c8`, after the tag. Against
  `ghcr.io/suitenumerique/calendars-backend:0.1.0` both probes 404, liveness fails, and the
  pod restarts forever while its logs show nothing but `Not Found: /__heartbeat__`.
- **Upstream's `:main` is stale.** Built 2026-06-24 from `9bb5200`, which is also before
  that commit. It has no `dockerflow` either, so it is not an escape hatch.

The fork publishes images from the same commit the chart was built from, so the chart and
the application move together — which is the property that matters and the reason not to mix
a `main` chart with a released image.

### Why `0.1.1` and not the fork's `main`

`v0.1.1` is `fe564fd` plus one CI fix, made in the fork because the fork is the PR staging
area (`adr/0108`). Both Dockerfiles end

```
ARG DOCKER_USER
USER ${DOCKER_USER}
```

and no workflow passed that build arg, so `USER` resolved to empty and every published image
ran as **root** — which the chart's own `runAsNonRoot: true` then refuses to start. kubelet
reports `container has runAsNonRoot and image will run as root` as a
`CreateContainerConfigError`: the container never starts, there are no logs, and the only
symptom is a Helm pre-install hook hanging until it times out.

**The chart is not at fault.** Docs' `src/helm/impress` sets the identical block — same four
keys, no `runAsUser` — and works, because `lasuite/impress-backend:v5.5.0` declares
`USER 1001:127`. Docs' reusable `docker-publish.yml` takes a `docker_user` input and its
callers pass it; Calendars' CI is a fork of that workflow with the input dropped. So the fix
is the missing input, not a chart override, and `1001:127` is what the sibling projects
publish rather than a number picked here. The frontend needed one thing more: its production
stage is `FROM caddy:2-alpine`, which ships no `USER` at all, so the build arg had nothing to
apply to. caldav keeps root deliberately — Apache binds :80.

That is why there is **no `securityContext` override in `release.yaml`**. There was one, and
it was deleted once the images were rebuilt: the correct end state is to be identical to the
other three apps. Upstream PR material, already validated by running it.

Worth knowing while reading any of this: **Kubernetes takes only the UID from an image's
`USER` and defaults the primary GID to 0.** Docs' pods run `1001:0`, not `1001:127`. That is
exactly why `chmod g=u /etc/passwd` is in these Dockerfiles — `/app/entrypoint` adds a passwd
entry for whatever uid it is handed, using the root group's write access.

## The frontend needs one capability back, and should not

`release.yaml` adds `NET_BIND_SERVICE` to the frontend container. It is never used — Caddy
listens on :8080 — and it is temporary.

`/usr/bin/caddy` in the official `caddy:2-alpine` image carries the **file capability**
`cap_net_bind_service=ep`, set so the server can bind :80. A file capability only grants what
is in the container's **bounding** set, and with `capabilities.drop: [ALL]` plus
`allowPrivilegeEscalation: false` (which sets `no_new_privs`) the kernel refuses the exec
outright:

```
exec /usr/bin/caddy: operation not permitted
```

That is the whole log. The pod is a `CrashLoopBackOff` with one line in it and nothing that
names capabilities.

This is the same failure mode Collabora taught this platform — `coolforkit-caps` carries file
caps, and `allowPrivilegeEscalation: false` breaks it identically. It is worth recognising by
shape: *a binary that exists, is executable, and cannot be executed* is almost always file
capabilities meeting a dropped bounding set.

Measured both ways before choosing: `--cap-drop=ALL --security-opt no-new-privileges`
reproduces it exactly, adding back this one capability fixes it, and an image with
`setcap -r /usr/bin/caddy` serves with ALL dropped and nothing added. **The last is the right
fix and it belongs upstream** — Docs sidesteps the whole thing by using
`nginx-unprivileged`, which ships no file caps. Delete this block when the image stops
carrying the capability.

## Dramatiq needs `KEYS`, and the Valkey ACL denies it

The broker user carries `+keys` on top of the platform's shared
`~* &* +@all -@dangerous`, and only for Calendars.

Dramatiq's dispatch is a Lua script that calls `KEYS`. `KEYS` is in `@dangerous`, which
every user on this platform denies, so the worker fails with

```
ACL failure in script: User calendars has no permissions to run the 'keys' command
```

and retries forever, three seconds at a time — a worker that looks alive, restarts nothing,
and silently processes no tasks. **Celery never calls `KEYS`**, which is why Docs and Drive
have never needed this and why nothing in the platform anticipated it.

The grant adds no reach these users do not already have — every pattern on this cluster is
`~*` — but it does sharpen the argument for narrowing them, because `KEYS` turns "can read
any key" into "can enumerate every key". Calendars is already the fourth application putting
session data in a store its neighbours can flush; this is the fifth reason.

## Email goes through a relay, and the config is in a Secret

RSVP and invitations are the product, so this is the one app where mail was never cosmetic.
It now sends through the smarthost in `smtp-credentials` — applied by hand into `office-data`
once (`docs/bootstrap.md` step 4b) and reshaped into this app's env names by
`smtp: {enabled: true, env: django}` in `deps.yaml`. Outbound TCP 25 is blocked from this
host by the provider (measured), so the relay answers on 587 or 465; a self-hosted MTA would
need the same smarthost anyway.

**Two things about that are load-bearing.**

`calendars-smtp` is attached to `backend.envFrom` — the *shared* block. Invitation mail is
sent by the Dramatiq worker, and the worker does not read `backend.django.*`. Mail put there
would fail in the one process that does the sending, with nothing wrong anywhere else. It is
the same trap as `DJANGO_CONFIGURATION`, one block up.

Nothing about the relay may also appear in `envVars`. A container's `env` beats `envFrom` for
the same name, so a leftover `EMAIL_BACKEND` line silently reinstates the old behaviour. This
app has two from-addresses and only one of them is a Django standard name, so
`CALENDAR_INVITATION_FROM_EMAIL` is a `secretKeyRef` onto the same `DEFAULT_FROM_EMAIL` key
rather than a second literal that could drift.

`MESSAGES_API_URL`/`MESSAGES_API_KEY` remains the other delivery path and remains unused —
Messages is not deployed.

Everything else works without it: calendars, sharing, CalDAV sync, the SPA.

## Single-tenant on purpose

`OIDC_USERINFO_ORGANIZATION_CLAIM` and `RESOURCE_EMAIL_DOMAIN` are both left empty. The
first puts every user in one organization derived from their email domain; the second
disables resource mailboxes. Both are correct for this platform, and organizations are hard
to introduce afterwards — if that ever changes, it is a decision to take before the user
table fills up, not after.

## The caldav pod is the one workload that is not `runAsNonRoot`

Apache binds `:80`, so the chart keeps `NET_BIND_SERVICE` and drops everything else. The
namespace enforces `baseline`, which permits this; `restricted` stays on audit/warn and
**will** flag it. That is the documented exception, not a regression.

## The gaufre, without a call to another country

Calendars is the one application in this suite where the app switcher needs **no workaround
at all**, and it is worth being precise about why.

`LaGaufreV2` (`@gouvfr-lasuite/ui-components` 1.0.0) renders the waffle *button* in
Calendars' own header and then hands the *panel* to a widget script it loads by URL, which
fetches a service list from a second URL. Both default to the French government's —
`static.suite.anct.gouv.fr/widgets/lagaufre.js` and `lasuite.numerique.gouv.fr/api/services`
— but unlike Drive's, both are **runtime settings**, read back by the SPA from
`/api/v1.0/config/`:

| Setting | Points at |
|---|---|
| `FRONTEND_LAGAUFRE_ENABLED` | `true`. Default `false`, which is why nothing rendered. |
| `FRONTEND_LAGAUFRE_WIDGET_PATH` | `https://calendars.${BASE_DOMAIN}/custom/gaufre.js` |
| `FRONTEND_LAGAUFRE_WIDGET_API_URL` | `https://calendars.${BASE_DOMAIN}/custom/services.json` |

Both files are ours (`gaufre.js`, `services.json`), served from Calendars' own origin by the
surround's `staticFiles` — the same nginx the Drive switcher uses. So Drive hides its gaufre
and rebuilds the button in `switcher.js`; Calendars keeps its button and replaces what sits
behind it. Nothing on the page reaches a third-party CDN.

`gaufre.js` is a drop-in for the upstream widget, and the contract it has to honour is the
queue the React component pushes to:

```js
window._lasuite_widget.push(["lagaufre", "init", cfg])
```

Two details in that contract are easy to get wrong. The component pushes from a `useEffect`,
so entries can arrive **after** the script has loaded — draining the array once is not
enough, `push` itself has to be replaced. And the effect re-runs on re-render, removing any
element with id `lasuite-widget-lagaufre-shadow` before each push — so the panel must carry
that id and `init` must be repeatable, tearing its own listeners down.

`services.json` is the **third** place this platform's inventory is stated to users, after
`apps/docs/release.yaml`'s `waffle.data.services` and `apps/drive/switcher.js`. An
application added to one and not the others is missing from a switcher.

**The one trap in the wiring:** the ConfigMap is generated in `apps/kustomization.yaml`
*without* `substitute: disabled`, because `services.json` needs `${BASE_DOMAIN}` resolved.
Flux substitutes over every key in that ConfigMap, so `gaufre.js` beside it is written with
**no dollar sign anywhere** — a template literal there would come out blanked, in a file no
check parses as JavaScript. `tests/build.sh` catches the reverse mistake (an unresolved
`${VAR}`), not this one.

Content type: nginx in `platform-app`'s `staticFiles` declares mime types for `js`, `css`
and `svg` only, so `services.json` is served as the default `application/octet-stream`.
`fetch(...).json()` does not look at it. Adding `json` to that `types` block is a one-token
chart change worth making the next time `platform-app` is released for another reason.

## Silent login

**Not enabled, and not enableable from here.** Drive skips its login-advertising page with
`FRONTEND_SILENT_LOGIN_ENABLED`; Calendars has no equivalent at any version, so an anonymous
visitor gets the home page and a "log in" button even when they already have a Keycloak
session from Docs or Drive.

Three things are missing, all in the application:

1. **`OIDC_AUTHENTICATE_CLASS` is unset**, so `authenticate/` is mozilla-django-oidc's stock
   view, which ignores `?silent=true` and never sends `prompt=none`. Drive sets it to
   `lasuite.oidc_login.views.OIDCAuthenticationRequestView`. Not overridable by environment:
   it is a plain class attribute in `settings.py`, not a `values.Value`.
2. **No `FRONTEND_SILENT_LOGIN_ENABLED` setting** and nothing publishing it through
   `ConfigView`.
3. **No frontend attempt.** `features/auth/Auth.tsx` sets `user = null` on a 401 for any page
   that is not `redirect`, which is the home page. Drive's `silentLogin.ts` — one redirect
   plus a `localStorage` retry timestamp so a genuinely logged-out visitor does not loop — is
   the whole of the missing logic.

The rest already works: `django-lasuite` 0.0.21 (the pinned version) **does** carry the
silent-aware request view and the callback that turns a `login_required` answer into a
redirect to the home page instead of the error page, and `core/authentication/views.py`
already subclasses that callback. So this is a change in the fork and an upstream PR, not a
values change — and it is a `0.1.2` image build, since the frontend half is compiled in.

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
  the application itself — see "Silent login" above.
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

Last: the waffle entry in `apps/docs/release.yaml` is already there, but the rendered theme
JSON is cached in Redis for 24h, so Calendars does not appear in the app switcher until that
key is deleted. See `apps/docs/README.md`.
