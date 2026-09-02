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
