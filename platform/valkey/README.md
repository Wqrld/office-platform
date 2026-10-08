# Shared cache and broker

Two instances, because eviction policy and persistence are **per-instance** settings that a
logical DB number does not separate (`history/design/06-datastores.md`):

| Instance | Policy | Why |
|---|---|---|
| `valkey-cache` | `allkeys-lru`, no persistence | Django cache. Losing it is harmless. |
| `valkey-broker` | `noeviction`, AOF on | Celery queue. An evicting broker silently drops queued tasks — data loss that presents as "some uploads never get processed", weeks later. |

So the broker is `noeviction` **at every size**: a size moves only its `maxmemory`
(`platform/overlays/size-*`). Eviction there is never a memory saving. An app that runs
Celery asks for both instances (`cache: {uses: [cache, broker]}` in its `deps.yaml`, and
`cache: [cache, broker]` in `charts/control-plane/apps.yaml`).

## ACLs are the only isolation here

This cluster's CNI enforces no NetworkPolicy (adr/0103), so any pod can reach these
instances. The per-user ACLs are therefore load-bearing, not defence in depth. `default` is
`off -@all` so there is no ambient access.

## Adding an application

Nothing here. The app's entry in `charts/control-plane/apps.yaml` (`cache: [cache, broker]`)
reaches the tenants chart as TENANTS_JSON, which generates the password, assembles the ACL
Secret and renders the permissions: `valkey-<instance>-acl-values`, a ConfigMap holding
`auth.aclUsers` that each HelmRelease here reads through `valuesFrom`. Every app gets the
instance's shared line (`valkeyAcl` in `charts/platform-tenants/values.yaml`); an app that
needs a command on top says so in its entry, `acl: {broker: +keys}`.

`+flushdb` is granted on the cache because Django's `cache.clear()` calls it and fails with
`ConnectionInterrupted` when it is disabled. It is *not* granted on the broker.

## Two users need more than the shared shape

- **Calendars' broker user carries `+keys`.** Dramatiq dispatches through a Lua script that
  calls `KEYS`, which is in `@dangerous`: without it the worker logs `ACL failure in script:
  User calendars has no permissions to run the 'keys' command` and retries forever, three
  seconds at a time, with the pod still Ready. Celery never calls `KEYS`. It grants no reach
  the user lacks (every pattern is `~*`), but it turns "can read any key" into "can
  enumerate every key", which makes the case below sharper.
- **Projects' cache user carries `+info`.** node_redis (Sails' sessions and socket.io
  adapter) sends `INFO` as its ready check, and without it the client never becomes ready.

## Isolation is per-credential, not per-key

ACL key patterns are `~*`, not `~<app>:*`. Valkey ACLs cannot scope by logical DB, so
key-level isolation would need every application to use a key prefix matching its pattern,
verified per app for the chart and for Celery's own keys — and a pattern an application
does not actually use is a cache that silently denies every write. So today an application
holding one app's credentials could read another's logical DB. The credential is the
isolation, and that is the decision.

A credential does not keep tasks apart, though. Docs, Drive and Messages share the broker's
db 0, and Docs and Drive both use Celery's default `celery` queue, so each worker took the
other's tasks and discarded them as unregistered. Every Celery app therefore gets
`DJANGO_CELERY_BROKER_TRANSPORT_OPTIONS={"global_keyprefix": "<app>:"}` (the profile's
`brokerOptions`, charts/platform-deps/templates/cache.yaml), which prefixes all of Kombu's
keys. That is also the prefix the broker's key patterns can be narrowed to, once Celery's
pub/sub channels are confirmed to carry it.

## Never add a `dataFrom` entry to `valkey-{cache,broker}-users`

That was the original shape and it does not work (`charts/platform-tenants/templates/valkey.yaml`).
All three measured against this cluster:

- `refreshInterval: "0"` means *written once and never again*, not "re-draw on a spec
  change". Adding an entry bumps `metadata.generation`, ESO leaves
  `status.syncedResourceVersion` on the previous generation, and it keeps reporting
  `Ready=True / secret synced` while the Secret never gains the key.
- Forcing the refresh re-draws every entry, so adding the Nth application rotates the other
  N−1 passwords and takes their caches and Celery brokers down until each is restarted.
- A `creationPolicy: Merge` ExternalSecret is refused with `SecretOwnedByOther`: ESO will
  not write into a Secret another ExternalSecret owns.

Hence the split. `valkey-user-<app>` generates and never changes; `valkey-{cache,broker}-acl`
only reads, so it is idempotent and free to change shape. The chart consumes the assembled
Secret.

What the original failure looks like, so it is recognisable:

```
Generating ACL entries for users
Using password from existing secret for user default
Using password from existing secret for user docs
ERROR: No password found for user drive
```

The Deployment sits in `Init:CrashLoopBackOff` with the previous pod still serving, the
HelmRelease times out, and the `platform` layer goes unhealthy. Loud and non-destructive — the
running cache is never interrupted.
