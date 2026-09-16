# ADR-0009: Garage via garage-operator, with external S3 as a first-class mode

## Status
Accepted. (Supersedes the Proposed version that left the choice open.)

## Context
Three applications need S3-compatible storage: Docs, Drive and Grist. They currently use
Bitnami MinIO, which ADR-0004 removes. MinIO's licensing and feature posture has shifted, so
"pin MinIO and forget it" is a decision with a known end date.

Some organisations running this platform will already have object storage — cloud S3, or an
on-premise appliance — and will not want another storage system to operate.

## Decision
**Two modes on one contract**, exactly as for Postgres (P4).

**`mode: managed`** — [Garage](https://garagehq.deuxfleurs.fr/) managed by
[garage-operator](https://github.com/rajsinghtech/garage-operator). Apache-2.0, installed
from `oci://ghcr.io/rajsinghtech/charts/garage-operator`, releases cosign-signed with SLSA
provenance and an SBOM. Requires cert-manager for its admission and conversion webhooks,
which we install anyway.

Its CRDs map cleanly onto the datastore contract:

| CRD | Our use |
|---|---|
| `GarageCluster` | one shared cluster in the platform layer |
| `GarageBucket` | one per consuming app, with quota |
| `GarageKey` | per-app S3 credentials, scoped to that app's bucket |
| `GarageAdminToken` | bootstrap admin secret, ESO-managed |
| `GarageNode`, `GarageReferenceGrant` | not needed initially |

`platform-deps` with `kind: objectstore, mode: managed` emits a `GarageBucket` plus a
`GarageKey`, and an ESO `ExternalSecret` reshapes the generated key into the canonical shape
(`endpoint`, `region`, `bucket`, `accessKeyId`, `secretAccessKey`, `useSSL`). No application
file changes between modes.

**`mode: external`** — any S3-compatible endpoint. Credentials come from the organisation's
secret store via `secretStoreRef`; `egressCIDR` is schema-required (ADR-0006 / `06-datastores.md`).
This is not a fallback, it is a supported first-class mode, and it must work from M3.

## Consequences

**The honest risk:** garage-operator is a young project under a personal namespace
(~250 stars, v0.7.x). ADR-0002 rejected Timoni partly on single-maintainer risk, and
intellectual consistency requires naming the same risk here.

Three things make it acceptable where Timoni was not:

1. **The blast radius is one release.** P4 means the app charts never learn what Garage is.
   Replacing the operator — with a different operator, plain Garage manifests, or external
   S3 — is a change to `platform-deps` and nothing else.
2. **The operator is the thin part.** Garage itself is a separate, established project from
   Deuxfleurs. If the operator stalls, Garage does not.
3. **External mode is the escape hatch that already exists.** An organisation that loses
   confidence in the managed path flips one value.

Timoni, by contrast, would have been the language every manifest was written in.

**Operational caveats to design around, from the operator's own documentation:**

- **Replication factor changes require a destroy and rebuild.** Pick the factor at install
  time and record it in the recovery inventory (`10-verification.md`).
- **PVC retention defaults to `Retain`** on scale-down and deletion. Correct default;
  it means deleting a cluster leaves volumes behind, which the runbook must state.
- **Avoid node-local storage pools.** They need Kubernetes 1.27+ *and* `privileged` Pod
  Security Admission on the namespace, which contradicts the security baseline in
  `02-architecture.md`. Use ordinary PVC-backed storage.
- **Operator v0.7.x requires Garage v2.0.0+** and drives everything through Admin API v2.
  Pin both, and treat a Garage major version as a deliberate upgrade like Keycloak.
- Multi-cluster federation needs externally-routable per-node RPC addresses. Not needed for
  single-cluster installs; do not enable it speculatively (P6).

**Region:** default it explicitly. An empty region causes flaky SigV4 signing in some SDKs —
a quirk inherited from the old repo, which hardcoded `eu-west-1` for exactly this reason.
