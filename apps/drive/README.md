# Drive

## What runs

`drive.${BASE_DOMAIN}`: La Suite's Drive — Django backend, frontend, Celery workers and one
Celery Beat, plus the `migrate`, `createsuperuser` and `configure-wopi` Jobs. Drive's shape
is close to Docs' with three differences: uploads go from the browser straight to the
object store (presigned, so `s3.<domain>` is published and the bucket has CORS —
`deps.yaml`), the chart has no `envFrom` (a `postRenderers` patch adds it — `release.yaml`,
`apps/README.md`, Conventions), and collaborative editing is WOPI to Collabora. How each
value is wired is commented on the value itself; below is what is not visible from the
files.

## Pins and forks

The fork's chart at git tag `v0.23.0-office.6`, path `src/helm/drive` (`wqrld-drive` in
`charts/control-plane/templates/sources.yaml`); the same tag publishes both images.

### The fork

Drive runs from `github.com/Wqrld/drive`: upstream `main` (after `v0.23.0`) plus document
thumbnails in the right panel, a celery task that posts each ready file to Collabora's
`/cool/convert-to/png` and stores the first page beside it (`WOPI_COLLABORA_OPTIONS`,
`ThumbnailServiceUrl`). The feature is on branch `feature/wopi-thumbnails`, meant for upstream;
the `office` branch adds one fork-only commit, `.github/workflows/ghcr.yml`, which publishes
`ghcr.io/wqrld/drive-backend` and `-frontend` on every `v*-office.*` tag. One tag pins chart
and both images.

Thumbnails exist for files that became ready after the deploy. Older ones get theirs with
`kubectl -n office-drive exec deploy/drive-backend -- python manage.py generate_thumbnails`.
Run it again after an upgrade that changes how thumbnails are stored: `v0.23.0-office.2`
versions their keys, so every file started without one. `v0.23.0-office.3` renders every
format a client opens (PDF included), known after the next discovery: run
`python manage.py trigger_wopi_configuration` first, then `generate_thumbnails`.
`v0.23.0-office.4` adds a list/grid toggle to the explorer (per browser, localStorage).

## Install order / first admin

`drive: {requires: [collabora]}` in `charts/control-plane/apps.yaml`: the `configure-wopi`
Job calls Collabora's discovery at install. The admin account is the `createsuperuser`
Job's; `USERNAME_FIELD` is `admin_email`, which upstream's `--email` does not set
(`release.yaml`).

### After a deploy: `e2e.py`

`./e2e.py` checks the whole thing end to end — OIDC login, a presigned upload, a download
through the media proxy, and a real Collabora editing session. Run it after any change to
the Gateway, the object store route, or either application. It needs a realm user:

```sh
pip install requests      # its one dependency
DOMAIN=example.org E2E_USER=<user> E2E_PASSWORD=<password> apps/drive/e2e.py
```

Nothing runs it for you: CI has no cluster (AGENTS.md), so it is a step after a deploy, by
hand, from any checkout that can reach `drive.<domain>`. It creates one file and deletes it.

## Gotchas

### The WOPI client configuration lives in an evicting cache

`configure_wopi_clients` fetches Collabora's discovery document and writes the extension and
mimetype tables into the **Django cache** — `valkey-cache` db 1, which is `allkeys-lru` and
does not survive a restart. On a miss `get_wopi_configuration()` returns an empty default
and every document reads as **"unsupported format"** in the UI. Nothing re-fetches on
demand; only the Celery Beat schedule refills it.

Upstream's default schedule is 03:00 daily, which makes that outage up to a day long. It
happened here the first time Valkey restarted. `WOPI_CONFIGURATION_CRONTAB_*` is therefore
set to every ten minutes; the task is one in-cluster HTTP GET.

To check, or to fix it immediately:

```sh
kubectl -n office-drive exec deploy/drive-backend -- python manage.py shell -c \
  "from django.core.cache import cache; c=cache.get('wopi_configuration'); \
   print(len(c['extensions']) if c else 'EMPTY')"
kubectl -n office-drive exec deploy/drive-backend -- python manage.py trigger_wopi_configuration
```

The install-time `configure-wopi` Job is not a reliable substitute: it is a plain Job, so a
Helm upgrade does not re-run it, and a Job that failed once stays failed.

### Envoy must not normalise the path

Collabora addresses an editing session by putting the WOPI source URL, percent-encoded,
*inside* the websocket path:

    /cool/https%3A%2F%2Fdrive.<domain>%2Fapi%2Fv1.0%2Fwopi%2Ffiles%2F<id>/ws

Envoy's defaults break that. `escapedSlashesAction` defaults to `UnescapeAndRedirect`, so
`%2F%2F` becomes `//`, slash merging collapses it to `/`, and the client is 307'd to a URL
whose WOPISrc is corrupt — every editing session redirects instead of upgrading, and the
document never opens. `platform/gateway/traffic.yaml` sets `KeepUnchanged` and
`disableMergeSlashes`.

That is Gateway-wide and has one consequence worth knowing: a `PathPrefix` match now sees
the raw path, so `/browser/dist%2Fadmin/…` no longer matches a deny rule written as
`/browser/dist/admin`. Collabora's admin console is therefore also disabled in coolwsd
itself rather than only at the edge — `apps/collabora/README.md`.

### An upload without Content-Type 500s

`upload_ended` reads `head_response["ContentType"]` unguarded. AWS S3 always returns it;
Garage returns it only if it was set on the PUT. A browser always sets it from the File
object, so this does not affect users — but any other client that omits it gets a 500 and
an item stuck in `analyzing`.

### Postgres needs three extensions, and only two are visible from the migrations

`django_ltree.0001` and `core.00006` both run `CREATE EXTENSION IF NOT EXISTS`, which the
non-superuser `drive` role cannot do — so its `postgres` entry in `charts/control-plane/apps.yaml` pre-creates
`ltree` and `pg_trgm` and those migrations become no-ops.

`unaccent` has **no migration at all**. `core/api/filters.py` filters on
`title__unaccent__icontains`, which fails at query time, not at migrate time. Leave it out
and every migration reports success while search is broken.

### Settings whose env name is not what you would guess

Drive uses django-configurations, and whether a setting is `DJANGO_`-prefixed depends on
whether its declaration passes `environ_prefix=None`.

| Setting | Env var | Note |
|---|---|---|
| `LANGUAGE_CODE` | `DJANGO_LANGUAGE_CODE` | **prefixed**, unlike Docs' bare `LANGUAGE_CODE` |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `EMAIL_*` | `DJANGO_…` | prefixed |
| `MEDIA_BASE_URL`, `LOGIN_REDIRECT_URL`, `AWS_S3_*`, `WOPI_*`, `OIDC_*` | bare | `environ_prefix=None` |
| `STORAGES_STATICFILES_BACKEND` | `DJANGO_STORAGES_STATICFILES_BACKEND` | the upstream dev values set it **unprefixed**, so it does nothing there |

We deliberately do not set the staticfiles backend, unlike Docs: Drive's Dockerfile runs
`collectstatic` at build with whitenoise's manifest storage, so the manifest is in the image
and the default is correct.

`FEATURES_INDEXED_SEARCH` defaults to **true**. Drive is not wired to Find, and left on the
indexing task fails on every upload — it is explicitly false.

## Upstream PRs

- **Document thumbnails** (`feature/wopi-thumbnails` in the fork, The fork above), meant for
  upstream. Once upstream releases the feature, point `sources.yaml` back at
  `suitenumerique/drive` and drop the image `repository` lines in `release.yaml`.
- **Content-Type on upload** (Gotchas, above): worth a one-line PR upstream,
  `.get("ContentType")`. No PR recorded yet.
