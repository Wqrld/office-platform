{{/*
Env-name profiles — adr/0106.

The platform reasons in canonical concepts (host, port, dbname, username, password). A
profile maps those concepts to the env var names one family of application expects, so the
Secret's keys ARE the app's env names and consumption is a single `envFrom` line.

`canonical` emits the key set from 06-datastores.md P4 and is the default. Add a profile
when a third app needs the same spelling; two is a coincidence, three is a feature (P5).
*/}}
{{- define "platform.profiles" -}}
postgres:
  canonical:
    host: host
    port: port
    dbname: dbname
    username: username
    password: password
    uri: uri
  django:
    # DB_ENGINE is a constant rather than a credential, but it belongs in the same Secret:
    # splitting it across a Secret and a values entry is how one of them gets forgotten.
    engine: DB_ENGINE
    host: DB_HOST
    port: DB_PORT
    dbname: DB_NAME
    username: DB_USER
    password: DB_PASSWORD

objectstore:
  # `publicEndpoint` is where a BROWSER reaches the bucket; `endpoint` is the in-cluster
  # Service. Emitted only for an app that presigns to the browser — adr/0110.
  canonical:
    endpoint: endpoint
    region: region
    bucket: bucket
    accessKeyId: accessKeyId
    secretAccessKey: secretAccessKey
    publicEndpoint: publicEndpoint
  django-s3:
    endpoint: AWS_S3_ENDPOINT_URL
    region: AWS_S3_REGION_NAME
    bucket: AWS_STORAGE_BUCKET_NAME
    accessKeyId: AWS_S3_ACCESS_KEY_ID
    secretAccessKey: AWS_S3_SECRET_ACCESS_KEY
    publicEndpoint: AWS_S3_DOMAIN_REPLACE

# Cache is addressed as a URL, not as parts: every consumer we have takes a connection
# string. The profile therefore names the env var per USE (cache, broker), not per concept.
cache:
  canonical:
    cache: CACHE_URL
    broker: BROKER_URL
  django:
    cache: REDIS_URL
    broker: DJANGO_CELERY_BROKER_URL
  # Dramatiq, not Celery. The third URL is what earns this its own profile: Dramatiq keeps
  # task results in a SECOND store, and that URL carries the password, so it cannot be
  # composed with a `valueFrom` in the app's own values — it has to come out of this
  # template. `results` deliberately points at the cache instance, not the broker: results
  # live for 30 days, and on the broker (`noeviction`, by design) a filled result set stops
  # the queue, while on the cache (`allkeys-lru`) a lost result is a `/tasks/<id>/` poll
  # that returns nothing. Same instance as `cache`, so it is the same ACL user.
  dramatiq:
    cache: REDIS_URL
    broker: DRAMATIQ_BROKER_URL
    results: DRAMATIQ_RESULT_BACKEND_URL

# Parts, not a URL: opensearch-py takes host and port separately and accepts no
# connection string. `indexPrefix` is the tenant boundary, not a tuning knob (adr/0111).
opensearch:
  canonical:
    host: host
    port: port
    username: username
    password: password
    useSSL: useSSL
    indexPrefix: indexPrefix
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
  canonical:
    backend: backend
    host: host
    port: port
    username: username
    password: password
    useTLS: useTLS
    useSSL: useSSL
    from: from
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
{{- end -}}

{{/*
Resolve one profile. Call with (list "postgres" "django") and it returns the map, or fails
with a message naming what was asked for — a typo here would otherwise render a Secret with
the wrong keys and present as a missing env var at runtime.
*/}}
{{- define "platform.profile" -}}
{{- $kind := index . 0 -}}
{{- $name := index . 1 | default "canonical" -}}
{{- $all := include "platform.profiles" . | fromYaml -}}
{{- $forKind := index $all $kind -}}
{{- if not $forKind }}{{ fail (printf "platform.profile: no profiles for datastore kind %q" $kind) }}{{ end -}}
{{- $profile := index $forKind $name -}}
{{- if not $profile }}{{ fail (printf "platform.profile: %s has no profile %q (have: %s)" $kind $name (keys $forKind | sortAlpha | join ", ")) }}{{ end -}}
{{- toYaml $profile -}}
{{- end -}}
