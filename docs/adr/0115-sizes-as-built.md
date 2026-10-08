# 0115 — The sizes as built: only `large` scales out

**Status:** accepted · **Date:** 2026-10-08 · **Amends:** `history/design/05-app-contract.md`
(the profile table)

## Context
The design set's profile table promised more than the sizes deliver. `medium` was to run
2 replicas of every frontend and backend with HPA and PDBs on, CNPG at 2 instances behind
a Pooler, and Garage at 3 nodes. `large` was to add HPA everywhere, enforced topology
spread, a Pooler, Garage at 3+ nodes, multi-node OpenSearch and a horizontally scaled
LiveKit. This ADR records what `apps/*/sizes/` and `platform/overlays/size-*/` set today.
It does not decide whether that is enough.

## Decision
The profiles are what the files set:

| Profile | Apps | Platform |
|---|---|---|
| **`small`** | 1 replica everywhere, no PDBs | the base, with smaller storage, memory and Keycloak resources |
| **`medium`** | 1 replica everywhere, no PDBs; more resources than `small` | the base as it is: CNPG 1 instance, Keycloak 1, Garage 1 node |
| **`large`** | components above 1 replica where the app allows, a `maxUnavailable: 1` PDB on each (`apps/<app>/sizes/platform-large.yaml`) | CNPG 3 instances, Keycloak 2; Garage still 1 node |

At every size:
- **No HPA.** The upstream charts' HPAs are off (Collabora, LiveKit), and replica counts
  are fixed.
- **No Pooler.** See `platform/postgres/README.md`.
- **Garage at one node with `replication.factor: 1`.** The factor cannot be changed in
  place.
- **Fixed counts the sizes don't set.** Collabora, the SFU and Drive's celery-beat
  (`apps/README.md`, "What a size may not decide").

## Consequences
- `medium` has no HA at the app or the datastore level. A node drain or a rollout is a
  short outage of each component, the same as on `small`. Its range of 50–500 people is
  about capacity, not availability.
- `large` is HA for the app tier and for Postgres and Keycloak, but not for the object
  store. A Garage node loss is still downtime.
- Bringing `medium` up to the design means raising backend and frontend replicas to 2 in
  each `apps/<app>/sizes/medium.yaml` and giving medium a PDB file in the `<app>-sizes`
  ConfigMap. `tests/profiles.py` checks that the replica counts and budgets agree. That
  change would supersede this ADR.
