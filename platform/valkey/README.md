# Shared cache and broker

Two instances, because eviction policy and persistence are **per-instance** settings that a
logical DB number does not separate:

| Instance | Policy | Why |
|---|---|---|
| `valkey-cache` | `allkeys-lru`, no persistence | Django cache. Losing it is harmless. |
| `valkey-broker` | `noeviction`, AOF on | Celery queue. An evicting broker silently drops queued tasks — data loss that presents as "some uploads never get processed". |

## ACLs are the only isolation here

This cluster's CNI enforces no NetworkPolicy (adr/0103), so any pod can reach these
instances. The per-user ACLs are therefore load-bearing, not defence in depth. `default` is
`off -@all` so there is no ambient access.

## The seam: adding an application touches this directory

The chart takes its ACL user list and its password Secret at the instance level, so a new
application needs a user here *and* its own app file — the one place the "one file per app"
property does not hold. Accepted for now (P5: an exception used once is an exception). If a
third application makes it annoying, the fix is an operator with a per-user CRD, not
per-app instances.

`+flushdb` is granted on the cache because Django's `cache.clear()` calls it and fails with
`ConnectionInterrupted` when it is disabled. It is *not* granted on the broker.

## Isolation is per-credential, not per-key

ACL key patterns are `~*`, not `~<app>:*`. Valkey ACLs cannot scope by logical DB, so
key-level isolation would require every application to set a Django `KEY_PREFIX` matching
its pattern — and a pattern the application does not actually use is a cache that silently
denies every write. So today an application that holds one app's credentials could read
another's logical DB.

Tightening this means verifying, per app, that the upstream chart exposes a cache key prefix
and that Celery's own keys honour it. Worth doing at the second application, not before.

## Adding an application's ACL user

Two files, and the order in them matters less than the shape:

1. `platform/valkey/{cache,broker}.yaml` — one line each under `auth.aclUsers`.
2. `platform/secrets/valkey-users.yaml` — a **new** `creationPolicy: Merge` ExternalSecret
   per instance. Do **not** add a `dataFrom` entry to the shared `valkey-*-users` objects.

The reason is a property of ESO that is easy to get backwards. `refreshInterval: "0"` does
not mean "re-draw when the spec changes"; it means the ExternalSecret is written once and
never again. Adding an entry to a generate-once object bumps its `metadata.generation`, ESO
leaves `status.syncedResourceVersion` pointing at the previous generation, and it goes on
reporting `Ready=True / secret synced` — while the Secret never gains the key.

What that looks like from the outside is Valkey's init container refusing to start:

```
Generating ACL entries for users
Using password from existing secret for user default
Using password from existing secret for user docs
ERROR: No password found for user drive
```

The Deployment sits in `Init:CrashLoopBackOff` with the previous pod still serving, so the
HelmRelease times out and the `30-platform` layer goes unhealthy — loud, and non-destructive.
This was measured in production while adding `drive`.

Forcing the refresh is worse than leaving it: `force-sync` re-draws every entry in the
object, so adding the Nth application rotates the passwords of the other N−1 and takes
their caches and Celery brokers down until each one is restarted. A `Merge` ExternalSecret
adds exactly one key and touches nothing else — verified against this cluster.
