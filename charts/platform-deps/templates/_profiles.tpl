{{/*
Env-name profiles — adr/0106.

The platform reasons in canonical concepts (host, port, dbname, username, password). A
profile maps those concepts to the env var names one family of application expects, so the
Secret's keys ARE the app's env names and consumption is a single `envFrom` line.

Add a profile when a third app needs the same spelling; two is a coincidence.
*/}}
{{- define "platform.profiles" -}}
postgres:
  django:
    # DB_ENGINE is a constant rather than a credential, but it belongs in the same Secret:
    # splitting it across a Secret and a values entry is how one of them gets forgotten.
    engine: DB_ENGINE
    host: DB_HOST
    port: DB_PORT
    dbname: DB_NAME
    username: DB_USER
    password: DB_PASSWORD
  # One connection string, for apps that take nothing else (Projects: knex, DATABASE_URL).
  # Safe to assemble unescaped: the platform's passwords carry no symbols (generator.yaml).
  url:
    url: DATABASE_URL

objectstore:
  # `publicEndpoint` is where a BROWSER reaches the bucket; `endpoint` is the in-cluster
  # Service. Emitted only for an app that presigns to the browser — adr/0110.
  django-s3:
    endpoint: AWS_S3_ENDPOINT_URL
    region: AWS_S3_REGION_NAME
    bucket: AWS_STORAGE_BUCKET_NAME
    accessKeyId: AWS_S3_ACCESS_KEY_ID
    secretAccessKey: AWS_S3_SECRET_ACCESS_KEY
    publicEndpoint: AWS_S3_DOMAIN_REPLACE
  # Projects. Path-style is a constant of Garage, not of the app, so it rides in the Secret.
  s3:
    endpoint: S3_ENDPOINT
    region: S3_REGION
    bucket: S3_BUCKET
    accessKeyId: S3_ACCESS_KEY_ID
    secretAccessKey: S3_SECRET_ACCESS_KEY
    forcePathStyle: S3_FORCE_PATH_STYLE

# Cache is addressed as a URL, not as parts: every consumer we have takes a connection
# string. The profile therefore names the env var per USE (cache, broker), not per concept.
cache:
  django:
    cache: REDIS_URL
    broker: DJANGO_CELERY_BROKER_URL
  # Dramatiq, not Celery. The third URL is what earns this its own profile: Dramatiq keeps
  # task results in a SECOND store, and that URL carries the password, so it cannot be
  # composed in the app's own values. Which instance `results` points at is the app's
  # choice (`cache.instances` in its deps.yaml).
  dramatiq:
    cache: REDIS_URL
    broker: DRAMATIQ_BROKER_URL
    results: DRAMATIQ_RESULT_BACKEND_URL

# Parts, not a URL: opensearch-py takes host and port separately and accepts no
# connection string. `indexPrefix` is the tenant boundary, not a tuning knob (adr/0111).
opensearch:
  find:
    host: OPENSEARCH_HOST
    port: OPENSEARCH_PORT
    username: OPENSEARCH_USER
    password: OPENSEARCH_PASSWORD
    useSSL: OPENSEARCH_USE_SSL
    indexPrefix: OPENSEARCH_INDEX_PREFIX

# The relay. Unlike every other kind here, none of this is generated in-cluster — it is one
# operator-supplied credential fanned out to four namespaces, so the profile's whole job is
# spelling. `backend` is the Django backend class: a constant rather than a credential, but
# it belongs in the same Secret as the host it points at, for the reason DB_ENGINE does.
#
# The two application spellings are NOT one prefix apart, which is why they are two profiles
# and not a `prefix:` value: Docs and Drive say EMAIL_FROM, Calendars says the stock Django
# DEFAULT_FROM_EMAIL.
smtp:
  # Calendars. `environ_prefix=None` on every EMAIL_* value in its settings module.
  django:
    backend: EMAIL_BACKEND
    host: EMAIL_HOST
    port: EMAIL_PORT
    username: EMAIL_HOST_USER
    password: EMAIL_HOST_PASSWORD
    useTLS: EMAIL_USE_TLS
    useSSL: EMAIL_USE_SSL
    from: DEFAULT_FROM_EMAIL
  # Docs and Drive. django-configurations with its default DJANGO prefix; the two settings
  # modules are identical in this block, which is what earns one profile for both.
  django-prefixed:
    backend: DJANGO_EMAIL_BACKEND
    host: DJANGO_EMAIL_HOST
    port: DJANGO_EMAIL_PORT
    username: DJANGO_EMAIL_HOST_USER
    password: DJANGO_EMAIL_HOST_PASSWORD
    useTLS: DJANGO_EMAIL_USE_TLS
    useSSL: DJANGO_EMAIL_USE_SSL
    from: DJANGO_EMAIL_FROM
  # Projects (nodemailer). No backend class and no STARTTLS flag: `SMTP_SECURE` is implicit
  # TLS, i.e. the relay's useSSL, and on 587 nodemailer upgrades with STARTTLS by itself.
  nodemailer:
    host: SMTP_HOST
    port: SMTP_PORT
    username: SMTP_USER
    password: SMTP_PASSWORD
    useSSL: SMTP_SECURE
    from: SMTP_FROM
{{- end -}}

{{/* An app family's spelling per kind, so a deps file says `env: lasuite` once. */}}
{{- define "platform.families" -}}
lasuite:   {postgres: django, cache: django, objectstore: django-s3, smtp: django-prefixed}
find:      {postgres: django, cache: django, opensearch: find}
calendars: {postgres: django, cache: dramatiq, smtp: django}
projects:  {postgres: url, cache: django, objectstore: s3, smtp: nodemailer}
{{- end -}}

{{/*
Resolve one profile: the kind's own `env`, else the family's. Call with (list $ "postgres"
$p.env); fails naming the alternatives, because a wrong key set presents as a missing env
var at runtime.
*/}}
{{- define "platform.profile" -}}
{{- $root := index . 0 }}{{ $kind := index . 1 }}{{ $name := index . 2 -}}
{{- $family := index (include "platform.families" . | fromYaml) ($root.Values.env | toString) | default dict -}}
{{- $name = $name | default (index $family $kind) -}}
{{- $forKind := index (include "platform.profiles" . | fromYaml) $kind -}}
{{- $profile := index $forKind ($name | toString) -}}
{{- if not $profile }}{{ fail (printf "%s.env must be one of: %s (or env: a family that has one)" $kind (keys $forKind | sortAlpha | join ", ")) }}{{ end -}}
{{- toYaml $profile -}}
{{- end -}}
