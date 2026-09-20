# 0102 — Pod Security Admission first; Kyverno deferred

**Status:** accepted · **Date:** 2026-09-02 · **Amends:** design set `adr/0102`

## Context
The design set makes Kyverno the invariant layer from M1: mutate the portable half of the
security context, validate the rest.

## Decision
Start with PSA `enforce: baseline`, `audit: restricted`, `warn: restricted` on every
namespace. No Kyverno yet.

## Reasoning
`enforce: restricted` rejects most upstream images unless something mutates their security
context first — which is precisely the mutation `adr/0102` warns breaks a fresh bootstrap
when applied cluster-wide to Keycloak, CNPG, Garage and DINUM's images.

Auditing `restricted` produces exactly the evidence needed: a list of which real pods fail
which control, on this cluster, with these images. Adopting Kyverno with that list is a
deliberate act. Adopting it beforehand is guesswork enforced by an admission webhook.

P6: an admission controller is an upgrade cycle owned forever. Two applications do not yet
justify one.

## Consequences
The gap between `baseline` and `restricted` is unenforced in the interim, and is visible in
audit annotations rather than assumed absent. Revisit when the audit log is non-empty and
understood, or when the third application lands.
