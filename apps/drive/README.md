# Drive

Upstream chart at git tag `v0.21.2`, path `src/helm/drive`. Everything below is a thing
that cost time to find.

Drive's shape is close to Docs' — Django + Next.js + Celery, same OIDC helper, same media
proxy — with three real differences: **uploads bypass the backend**, **the chart has no
`envFrom`**, and **collaborative editing is WOPI to Collabora**, not a y-provider.

## Uploads go from the browser straight to the object store

`core/api/utils.generate_upload_policy` returns a presigned `PUT` URL and the browser
writes the file body to S3 itself. There is no in-application fallback, so without a
publicly reachable object store Drive cannot upload a file at all.

A SigV4 signature covers the host, so the URL has to be signed against a host the browser
can reach — that is what `AWS_S3_DOMAIN_REPLACE` is for, set by `drive-deps` as
`objectstore.publicEndpoint`. `platform/objectstore/public-route.yaml` publishes Garage at
`s3.<domain>` for the `/drive/` path prefix only. **`adr/0110` is the argument; read it
before adding a prefix to that route.**

Measured against this cluster's Garage while building this:

- botocore presigns **path-style** against a custom `endpoint_url`, so the bucket is a path
  prefix and the route's scoping is a real bound.
- Garage accepts a signed `x-amz-acl: private` on a presigned PUT (200 with and without),
  so `AWS_S3_UPLOAD_ACL` stays at its default rather than needing the `default` escape
  hatch other object stores need.

CORS is on the route, not on the bucket: Garage's bucket CORS config is not reachable
through the operator's CRDs.

## The chart has no `envFrom`, so the secrets arrive by post-render

`drive.common.env` renders `backend.envVars` as a plain `env:` list. There is no
`envFrom` key anywhere in the chart, so consuming the five Secrets `drive-deps` creates the
straightforward way would mean about forty hand-written `secretKeyRef` entries.

`release.yaml` uses a Flux `postRenderers` kustomize patch instead. Two things about it are
worth knowing before touching it:

- **kustomize matches `name` as a full-string regex.** `^drive-backend` matches *only* the
  object literally called `drive-backend` — it is not a prefix match. `drive-backend.*` is
  what selects the set. This was measured, not assumed: `^drive-backend` patched 1 of 10
  workloads and the mistake is invisible until a pod crash-loops.
- **The selector is a security boundary.** `drive-backend.*` covers the backend Deployment,
  both Celery Deployments, three Jobs and four CronJobs, and does not cover
  `drive-frontend`. The frontend must never hold the database password or the OIDC client
  secret.

A CronJob needs its own patch: the pod spec sits under `spec.jobTemplate.spec.template`
and no kustomize target spans both shapes. The chart emits its CronJobs inside a
`CronJobList`, which kustomize flattens before patching — verified.

Verify after a chart bump:

```sh
./check-secrets.sh                     # clones the tag sources.yaml pins
./check-secrets.sh /path/to/checkout   # or use one you already have
```

It reads the patches out of `release.yaml` rather than restating them, renders the chart,
applies them, and asserts that every `drive-backend*` workload carries all five Secrets and
that `drive-frontend` carries none.

If upstream renames its objects the patch matches nothing and the pods start with no
database configuration, which crash-loops immediately. Loud, but only at deploy time.

**What would remove this:** `envFrom` support in the upstream chart. That is a small change
to `src/helm/drive/templates/_helpers.tpl` and worth a PR — `adr/0108`.

## `USERNAME_FIELD` is `admin_email`, not `email`

Drive's `User` has both. `email` is the OIDC identity address and is nullable; `admin_email`
is the unique login field. The chart's default `createsuperuser` command passes only
`--email`, which leaves the username field unset — and `--noinput` cannot fill it in.

`release.yaml` replaces the command with an idempotent `manage.py shell` script keyed on
`admin_email`, setting both addresses to the same value so the Django admin login and the
OIDC identity are one account. The same replacement also fixes the reason Docs needed one:
the Job is not a Helm hook, so a `createsuperuser` that fails on an existing account is
permanent noise on every reconcile.

## WOPI: how the Collabora integration actually wires up

| Setting | Value | Why that side |
|---|---|---|
| `WOPI_CLIENTS` | `collabora` | names the client; each name `N` is then read back as `WOPI_<N>_DISCOVERY_URL` |
| `WOPI_COLLABORA_DISCOVERY_URL` | in-cluster Service | Drive fetches the capability list itself, server to server |
| `WOPI_SRC_BASE_URL` | `https://drive.<domain>` | Collabora calls back from **outside** the cluster |

The URLs *inside* the discovery document are Collabora's public ones, because coolwsd
builds them from its own `server_name` — those are what the browser loads. So the discovery
fetch is internal and everything it describes is external; getting that backwards gives a
working discovery fetch and an editor iframe pointed at `localhost`.

`/api` therefore has to stay publicly routable for reasons beyond the browser: the WOPI
host endpoints live at `/api/v1.0/wopi/files/…` and Collabora reaches them over the
internet.

The `configure-wopi` Job runs at install and needs Collabora up, which is why the
`HelmRelease` has a cross-namespace `dependsOn`. Celery Beat re-runs the configuration on
the `WOPI_CONFIGURATION_CRONTAB_*` schedule, so a one-off failure heals — and so a
Collabora upgrade is picked up without a Drive deploy. That is why Beat is enabled.

## Postgres needs three extensions, and only two are visible from the migrations

`django_ltree.0001` and `core.00006` both run `CREATE EXTENSION IF NOT EXISTS`, which the
non-superuser `drive` role cannot do — so `platform/postgres/databases.yaml` pre-creates
`ltree` and `pg_trgm` and those migrations become no-ops.

`unaccent` has **no migration at all**. `core/api/filters.py` filters on
`title__unaccent__icontains`, which fails at query time, not at migrate time. Leave it out
and every migration reports success while search is broken.

## Settings whose env name is not what you would guess

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

`FEATURES_INDEXED_SEARCH` defaults to **true**. There is no search service on this
platform, and left on the indexing task fails on every upload — it is explicitly false.

## Overriding `celeryWorkers` is a render-time nil-pointer unless you restate `probes`

`backend_celery_worker.yaml` dereferences `$worker.probes.liveness` with no nil guard, and
overriding `celeryWorkers` replaces upstream's whole list — defaults included. An entry
without `probes` fails at `helm template` with

```
nil pointer evaluating interface {}.liveness
```

which at least fails at render rather than at runtime. Upstream's probes are restated in
`release.yaml`.

## One Celery worker, not three

The upstream dev values run three workers, on `default`, `mirror` and `malware_detection`.
That split only exists if `DJANGO_CELERY_TASK_ROUTES` sends tasks to those queues, and it is
not set, so everything lands on the default queue. One worker with `--concurrency 2` drains
it. Without an explicit concurrency Celery preforks one process per CPU — ten on this node,
each a whole Django — and is OOMKilled seconds after a healthy-looking startup, which is
the bug Docs hit first.
