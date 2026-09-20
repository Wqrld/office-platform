# 06 — Datastores

## The contract

The app chart knows **only** that a Secret exists with a canonical key set. It never learns
what CloudNativePG is (P4). That is what makes bring-your-own-database a config change
rather than a rewrite.

| Kind | Canonical secret keys |
|---|---|
| `postgres` | `host`, `port`, `dbname`, `username`, `password`, `uri` |
| `cache` | `host`, `port`, `username`, `password`, `db`, `uri` |
| `objectstore` | `endpoint`, `region`, `bucket`, `accessKeyId`, `secretAccessKey`, `useSSL` |
| `opensearch` | `host`, `port`, `username`, `password`, `useSSL`, `indexPrefix` |

`platform-deps` guarantees that shape regardless of source, using an ESO
`ExternalSecret` with a `template` block to reshape whatever the provider emits.

## Scope

The proposal models everything per-app. Two of ours are genuinely shared, so the chart needs
a scope dimension:

```yaml
scope: app     # a Database/user on a shared server, or a dedicated instance
scope: shared  # one instance many apps consume; each app gets its own credentials
```

| Datastore | Scope | Consumers |
|---|---|---|
| Postgres | `app` (Database + role on the shared CNPG Cluster) | 10 apps |
| Cache | `shared` (two instances — cache and broker; per-app ACL user + logical DB) | 11 apps |
| OpenSearch | `shared` (one instance, per-app index prefix) | find, docs |
| Object storage | `app` (Garage bucket + scoped key) on a shared cluster | docs, drive, grist |

The kinds are named for the **contract**, not the implementation — `cache`, not `valkey`;
`objectstore`, not `garage` — for the same P4 reason the app charts never learn what
CloudNativePG is.

The per-app *contract* is identical in both cases, so splitting a shared instance later is a
config change, not a rewrite.

## Managed vs. external

Both modes, all kinds, from the start. The app file is byte-identical either way.

```yaml
# managed
kind: postgres
mode: managed
scope: app
postgres:
  clusterRef: {name: shared-pg, namespace: databases}
  database: docs
```

```yaml
# external
kind: postgres
mode: external
external:
  host: docs.abc123.eu-west-1.rds.amazonaws.com
  port: 5432
  database: docs
  sslMode: verify-full
  caSecret: rds-eu-west-1-ca
  credentials: {secretStoreRef: vault, remoteKey: prod/docs/db}
  egressCIDR: 10.42.7.0/24
```

Build the switch for Postgres, cache and object storage at once. The same request arrives
for all three, and retrofitting mode-awareness into a chart that assumed managed is the
expensive version.

### The five things that break in external mode

1. **NetworkPolicy egress.** Default-deny silently blocks the external host and the symptom
   looks like a credentials failure. Make `egressCIDR` **schema-required** when
   `mode: external`.
2. **`dependsOn` stops working.** Flux cannot wait on what it does not manage. The library's
   generated wait-init-container (`04-platform-charts.md`) covers this.
3. **Connection pooling disappears.** CNPG gives you PgBouncer via the `Pooler` CR; RDS does
   not. External mode must deploy its own or you exhaust connections under load. Django apps
   with Celery workers are exactly the workload that does this.
4. **TLS becomes non-trivial.** `verify-full` plus a per-provider CA bundle that rotates.
5. **Backup responsibility transfers.** Record it per app so the recovery list in
   `10-verification.md` stays honest.

### Preflight

You cannot test against everyone's database in CI, so test at install time. A
`pre-install`/`pre-upgrade` Job asserts: server version in range, required extensions present
(Docs and Drive need `pg_trgm` and `unaccent`), role has its grants, TLS negotiated as
configured. Ten lines of `psql`. Turns "someone pointed us at Postgres 12 and the app
half-works" into a failed install with a clear message.

## Per-kind notes

### Postgres — CloudNativePG

Ten apps need it: docs, drive, meet, conversations, calendars, find, grist, people,
element/synapse, keycloak. (ESS ships its own PostgreSQL sub-chart — disable it and point
Synapse and MAS at the shared cluster, or accept a second Postgres you also have to back up.)

**Decided: one shared `Cluster`**, with a `Database` and `Role` per app. The old repo runs a
cluster per app (`docs-cluster-rw`, `meet-cluster-rw`, …) — roughly 27 pods, nine backup
configurations and nine things to upgrade, for applications inside one trust boundary.
Shared is ~3 pods, one backup configuration, one upgrade.

Keep it a values choice so an organisation with a stricter trust boundary can split without
touching an application file. Two things follow from sharing:

- **One PgBouncer `Pooler`** in front of it. Ten Django apps, several with Celery workers, is
  exactly the connection-count workload that needs pooling. **Two `Pooler`s, in fact**:
  transaction mode for the application (which is what saves the connections) and session
  mode — or a direct `-rw` connection — for migration Jobs and `manage.py` shells, because
  advisory locks, `SET` statements and session-scoped state do not survive transaction
  pooling. Django's `CONN_MAX_AGE` must be `0` behind a transaction pooler. Getting this
  wrong shows up as migrations that hang rather than fail.
- **Per-app roles with no cross-database grants**, so "shared server" does not become
  "shared data". Kyverno should assert it.

**A conflict to resolve, not ignore:** La Suite's Django apps run migrations that create C
extensions, which normally requires `SUPERUSER`. `lasuite-platform` grants it and flags the
compromise. On a *shared* cluster, `SUPERUSER` per app defeats the isolation above.

The fix is to **pre-create the extensions** — CNPG's `Database` CR declares them
(`pg_trgm`, `unaccent`) so the app's own role never needs to. `CREATE EXTENSION IF NOT
EXISTS` on an extension that already exists is a no-op and does not check privileges, so the
app's migration succeeds unprivileged. Declarative `Database` objects and their `extensions`
field are recent CNPG features — pin a version that has them and record the minimum at M3. The preflight Job below then
asserts they exist, turning a half-broken migration into a clear failed install.

Synapse's driver value is `psycopg2`, not `postgresql` — a per-app quirk that belongs in the
app's values, not the datastore contract.

### Cache — Valkey

Replaces Bitnami Redis. Eleven apps use it for the Django cache and as the Celery broker.
Recommend **shared instances with per-app ACL users and logical DBs**, not eleven instances —
eleven is eleven things to patch, monitor and back up for a workload that is almost entirely
ephemeral.

**But two shared instances, not one.** Eviction policy and persistence are per-*instance*
settings; a logical DB number does not separate them. A cache wants `maxmemory` with
`allkeys-lru` and no persistence. A Celery broker must have **no eviction policy at all** —
under memory pressure an evicting instance silently drops queued tasks, which is a data-loss
bug that presents as "some uploads never get processed". So:

| Instance | Policy | Consumers |
|---|---|---|
| `cache` | `maxmemory-policy: allkeys-lru`, no AOF | every app's Django cache |
| `broker` | `maxmemory-policy: noeviction`, AOF on | Celery in docs, drive, find, people |

Both sit behind the same contract (`uses: [cache, broker]` in the app file yields two secrets,
or one for apps with no Celery), so consolidating or splitting further later is a values
change. This is the one place the "one shared instance" instinct costs correctness rather
than only blast radius.

Note that Celery here uses Redis as its broker. There is no AMQP anywhere in this suite —
see `adr/0007` on not building RabbitMQ support.

`lasuite-platform` runs exactly this shape in practice, with an explicit DB-number
allocation (docs cache 0 / docs celery 1 / drive cache 2 / drive celery 3 / …). Ours is
allocated by `platform-deps` rather than by hand, but the allocation must be **recorded
and stable** — a silently reassigned DB number is a cache that reads someone else's data.

Two behaviours to decide deliberately rather than inherit:

- **`FLUSHDB`/`FLUSHALL` disabled** breaks Django's `cache.clear()` with
  `ConnectionInterrupted`. Bitnami disabled them by default; choose explicitly for Valkey.
- **Cache and broker on one instance** means a broker backlog can evict cache entries.
  Acceptable at this scale; separate DBs do not separate memory.

### Object storage — Garage

Three apps need S3: docs, drive, grist. **Garage, managed by
[garage-operator](https://github.com/rajsinghtech/garage-operator)** (Apache-2.0,
`oci://ghcr.io/rajsinghtech/charts/garage-operator`, cosign-signed with SLSA provenance).
Requires cert-manager for its webhooks, which we install anyway. See `adr/0009`.

One shared `GarageCluster` in the platform layer; per-app resources from `platform-deps`:

```yaml
kind: objectstore
mode: managed
scope: app
garage:
  clusterRef: {name: shared-garage, namespace: storage}
  bucket: docs
  quota: {maxSize: 200Gi}
```

emits a `GarageBucket` and a `GarageKey` scoped to it, plus an ESO `ExternalSecret` that
reshapes the generated credentials into the canonical key set. `mode: external` points at any
S3-compatible endpoint with credentials from the organisation's secret store — **a
first-class mode, not a fallback**; it must work from M3.

Design around these, all from the operator's own documentation:

- **Replication factor cannot be changed in place** — it requires destroy and rebuild. Choose
  it at install time and record it in the recovery inventory.
- **PVC retention defaults to `Retain`.** Correct, but deleting a cluster leaves volumes
  behind; say so in the runbook.
- **Do not use node-local storage pools.** They require `privileged` Pod Security Admission,
  which contradicts our security baseline. Use ordinary PVC-backed storage.
- **Pin Garage and the operator together.** Operator v0.7.x needs Garage v2.0.0+ via Admin
  API v2; treat a Garage major version like a Keycloak major version.
- **Do not enable multi-cluster federation** — it needs externally-routable per-node RPC
  addresses and we have no requirement for it (P6).
- **Set `region` explicitly.** An empty region causes flaky SigV4 signing in some SDKs; the
  old repo hardcoded `eu-west-1` for exactly this reason.
- **Expect SDK checksum incompatibility, and model it.** Since January 2025 newer AWS SDKs
  send checksum algorithms that non-AWS S3 implementations may not support.
  `lasuite-platform` handles this with an `s3.provider` switch that injects
  `AWS_REQUEST_CHECKSUM_CALCULATION=WHEN_REQUIRED` and
  `AWS_RESPONSE_CHECKSUM_VALIDATION=WHEN_REQUIRED` for affected providers. **Garage is not
  AWS**, so verify this against Docs and Drive during M3 and carry a `provider:` field on the
  objectstore contract from the start — it is one value now and an emergency later.
- **Buckets are per-app and not shared.** Docs and Drive each get their own; there is no
  cross-app file access today (see `08-app-inventory.md` on the blocked Docs↔Drive
  integration).
- **Say who owns lifecycle and retention on each bucket, per app.** The contract creates a
  bucket and a quota and stops there — nothing in it decides whether Docs' orphaned media is
  ever deleted, how long Drive keeps a soft-deleted file, or whether object versioning is on.
  Some of that is the application's own retention setting and some is the bucket's, and the
  two disagree by default. Record the answer per app in the recovery inventory
  (`10-verification.md`) alongside backup responsibility: an unbounded bucket behind a quota
  is an outage with a date on it, and a bucket the app thinks it has emptied but has not is a
  retention problem for a public-sector operator.

### Search — OpenSearch

One shared instance. `find` provides cross-app full-text search; Docs integrates with it.

**Resolve the contradiction the old repo left open.** The canonical secret shape above has
`username` and `password`, and the scope table says "per-app index prefix" with per-app
credentials — but the working configuration inherited from the old repo is
`DISABLE_SECURITY_PLUGIN: "true"`, which means *no* users, *no* authentication and *no*
index-level authorisation. Those cannot both be true. Two honest options:

- **Security plugin on** (recommended once there is a second consumer): internal TLS from
  cert-manager, an OpenSearch role per app scoped to its index pattern, credentials via ESO.
  The canonical secret shape then means what it says. Costs a day of `securityconfig` work
  and a certificate rotation story.
- **Security plugin off**: then say so — `username`/`password` are ignored, the instance is
  protected only by NetworkPolicy, and any consumer can read any index. Acceptable while
  Find is the only real consumer inside one trust boundary; not acceptable as a silent
  default once several apps hold different data.

Pick at M6, when Find is built, and record it. Whichever is chosen, consumers need
`OPENSEARCH_USE_SSL` set to match — the internal endpoint is plain HTTP on 9200 today, and
the official chart enables its demo security config unless told otherwise.

Hybrid search requires an embedding API key. Leave it disabled unless AI is configured;
plain full-text search works without it.

After a fresh deploy or an outage, indices must be rebuilt — that is a bootstrap Job
(`04-platform-charts.md`), not a runbook step.
