# 0106 — Canonical concepts, app-shaped keys, named profiles

**Status:** accepted · **Date:** 2026-09-03 · **Amends:** design set `history/design/06-datastores.md` (P4)

## Context
`history/design/06-datastores.md` states P4: the app chart knows **only** that a Secret exists with a
canonical key set — `host`, `port`, `dbname`, `username`, `password`, `uri` for Postgres,
and equivalents for cache, objectstore and opensearch.

Docs, built first, did the opposite. `docs-postgres` carries `DB_HOST`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`; `docs-s3` carries `AWS_S3_ACCESS_KEY_ID` and friends. The keys
*are* the application's env var names, so the chart consumes the whole Secret with one
`envFrom` line and no value is ever spliced into Helm values. The build notes of the time (not kept in this repo) recorded this
as an open question rather than a decision: "canonical secret keys, or per-app env-shaped
like `docs-s3`".

Both are technically available. DINUM's chart renders `valueFrom` when an `envVars` value
is a map, so canonical keys plus per-key `secretKeyRef` would work for Docs. That is not
true of upstream charts generally — `envFrom` is close to universal, a map-valued env entry
is not.

## Decision
`platform-deps` holds the **canonical concepts** internally and emits **app-shaped keys**,
chosen by a named profile.

```yaml
postgres:
  database: docs
  env: django          # DB_ENGINE, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
objectstore:
  bucket: docs
  env: django-s3       # AWS_S3_ACCESS_KEY_ID, AWS_S3_SECRET_ACCESS_KEY, …
```

`env: canonical` is the default and emits exactly the P4 key set. A profile is a map from
canonical concept to key name, defined once in `platform-lib`; an app needing a spelling no
profile covers passes the map inline.

## Reasoning
The canonical key set was the right idea attached to the wrong artefact. What P4 actually
wants is **one vocabulary the platform reasons about** — so a second app reuses a shape, a
datastore swap does not become an app change, and `platform-deps` can validate what it
emitted. None of that requires the *Secret's* keys to be the canonical names. It requires
the *chart* to know them.

Emitting app-shaped keys keeps the property Docs proved is worth having: consumption is one
`envFrom` line, so an app file carries no per-variable mapping, and no credential passes
through Helm values on its way into the pod. Canonical keys would cost ~15–20 mapping lines
per app and would depend on each upstream chart supporting map-valued env entries.

Profiles are what make this reuse rather than per-app drift. Docs and Messages are both
Django; both get `env: django` and therefore the same spelling, from one template.

## Consequences
- The canonical names survive as `platform-lib`'s internal vocabulary and as the
  `canonical` profile — they are not deleted, they stop being the wire format.
- `docs-s3`'s existing shape becomes the `django-s3` profile rather than a deviation to fix.
- A profile is a shared surface: changing one changes every app using it, so profiles are
  versioned with the chart and covered by golden files.
- An app whose spelling no profile covers passes an explicit map. Three apps needing the
  same inline map means it should have become a profile (P5).
