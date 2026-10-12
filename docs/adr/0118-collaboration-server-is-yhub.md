# 0118 — Docs' collaboration server is yhub; the legacy documents are migrated in place

**Status:** accepted · **Date:** 2026-10-12

## Context
Docs 6.0.0 (upstream `src/helm/impress`, tag `v6.0.0`) replaces the `y-provider` as the
collaboration server. The live state of every document now sits in yhub (`lasuite/impress-yhub`):
the websocket, the document routes, and a PostgreSQL database of its own, with Valkey for the
live stream. The `y-provider` keeps only the conversion service. The content of a document
is no longer a file in the object store, so the existing documents must be handed over to
yhub, or they open empty (upstream `UPGRADE.md`, 6.0.0).

Our surround routed `/collaboration/` to the `y-provider`, and the binding check caught the
upstream PodDisruptionBudget that yhub brings. A tag bump alone would have left the editor
talking to a server the backend no longer uses.

## Decision
- **yhub replaces the y-provider on `/collaboration/`.** The surround routes the websocket
  (`/collaboration/ws/`) and the five document routes upstream publishes (`ydoc`, `activity`,
  `changeset`, `rollback`, `jwks`) to `docs-yhub`. The backend-only routes stay in-cluster.
- **yhub gets its own database** (`yhub`, owned by the docs role) created by the tenants
  chart, through `databases:` in the app's `apps.yaml` entry. Its schema comes from the init-db
  job the chart runs on each release.
- **yhub shares Valkey `cache`**, db 1, with the backend, under the key prefix `yhub`. Its
  client needs `INFO` and `KEYS`, both `@dangerous`, so the docs user gets `+info +keys` on the
  `cache` instance (`acl:` in `apps.yaml`). That widens the backend's ACL slightly; yhub has no
  user of its own.
- **The keys are chart-generated.** `jwtKeys.enabled` makes the chart's job create the backend
  and yhub RSA keys once, in a secret both mount read-only. Keys never pass through Helm values.
- **The migration runs in place.** `SOFT_MIGRATION=true` on yhub, reading the docs bucket
  through the docs S3 key, before anyone signs in; then `migrate_documents` backfills the
  corpus; then `SOFT_MIGRATION` goes false. The legacy `{id}/file` objects and their versions
  stay where they are.
- **One replica per size below `large`; two at `large`,** with a PDB at `large` only (ADR 0115).
  The worker runs inside each server (chart default), not as a separate deployment.

## Reasoning
Routing the websocket to yhub and nothing else is the only split under which the editor and
the backend agree on where a document lives. A second Valkey user per app would be cleaner, but
the platform's ACL model is one user per app per instance, and the `+info +keys` widening is
bounded to the `cache` instance the backend already owns. The migration reads the docs bucket
with the docs key rather than a read-only key of its own: a read-only key needs a Garage grant
the tenants chart does not yet express, and the backend already holds the same key. That is a
known gap, not the design.

## Consequences
- A tag bump is no longer a tag bump: `apps/docs/`, `apps/docs/sizes/`, the tenants chart and
  `charts/control-plane/apps.yaml` change together, with the goldens.
- Live editing drops for the duration of the upgrade. While `SOFT_MIGRATION` is on, a document
  nobody has opened yet is seeded from its legacy snapshot on first open. Once it is off, a
  document the backfill has not covered opens empty, so the backfill runs in the window.
- The `y-provider` is now only a converter; its websocket settings are gone.
- `SOFT_MIGRATION` stays `true` until the backfill has covered the corpus, then goes false in
  a follow-up release. Until then, a document nobody has opened is seeded from its legacy
  snapshot on first open.
- A read-only legacy key is still to do: a Garage grant for the migration, then a switch of
  the `LEGACY_S3_*` source in `apps/docs/release.yaml`.
