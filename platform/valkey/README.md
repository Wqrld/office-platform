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
