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

Two files:

1. `platform/valkey/{cache,broker}.yaml` — one line each under `auth.aclUsers`.
2. `platform/secrets/valkey-users.yaml` — a new `valkey-user-<app>` ExternalSecret, and one
   line per assembler.

Never add a `dataFrom` entry to `valkey-{cache,broker}-users`. That was the original shape
and it does not work; the file's header comment has the full account. Short version, all
three measured against this cluster:

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

## One user needs more than the shared shape

Every ACL user here is `~* &* +@all -@dangerous`, plus `+flushdb` on the cache. Calendars'
BROKER user also carries `+keys`: Dramatiq dispatches through a Lua script that calls `KEYS`,
which is in `@dangerous`. Celery does not, so this is the first application to need it.

The symptom if it is ever dropped is quiet — `ACL failure in script` in the worker log and a
queue that never drains, with the pod still Ready.
