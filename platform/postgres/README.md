# Shared Postgres

One CNPG `Cluster`. Each application's `Database` and `DatabaseRole` is rendered by
`platform-tenants` from one line in its values, so adding an application never edits this
directory.

## No connection pooler

Five Django apps with their workers sit well under `max_connections: 200`. A transaction-mode
`Pooler` is the answer when that pressure appears, not before: it is a correctness trap
(Django's `CONN_MAX_AGE` must be `0` behind it, and getting it wrong presents as migrations
that hang), and migration Jobs would have to stay on `office-pg-rw` either way.

## Backups — NOT YET CONFIGURED

CNPG backs up via Barman to object storage; Garage exists, the Barman configuration does
not. **This cluster has no automated backup.** The one irreplaceable dataset
(legacy Docs) is held as an offline dump under `backups/` in the working tree.
