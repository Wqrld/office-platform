# Shared Postgres

One CNPG `Cluster`. Each application gets a `Database` and a `DatabaseRole` emitted by
`platform-deps`, so adding an application never edits this directory.

## No connection pooler, deliberately

`06-datastores.md` calls for two PgBouncer `Pooler`s (transaction mode for the app, session
mode for migrations). That is the right answer for ten Django apps with Celery workers. It is
not yet the right answer for one: a pooler here would be an unused component plus a real
correctness trap, because Django's `CONN_MAX_AGE` must be `0` behind a transaction pooler and
getting that wrong presents as migrations that hang rather than fail.

**Add a transaction-mode `Pooler` when** a second Django application lands, or when
`max_connections` pressure actually appears. Point applications at the pooler service and set
`CONN_MAX_AGE=0`; leave migration Jobs on `office-pg-rw`.

## Backups — NOT YET CONFIGURED

CNPG backs up via Barman to object storage, which does not exist until the object-store layer
lands. **Until then this cluster has no automated backup.** The one irreplaceable dataset
(legacy Docs) is held as an offline dump under `backups/` in the working tree.
