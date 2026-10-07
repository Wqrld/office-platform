# 0103 — NetworkPolicy is emitted but NOT enforced on this cluster

**Status:** accepted · **Date:** 2026-09-02 · **Corrects:** design set `history/design/02-architecture.md`

## Context
The design set treats default-deny NetworkPolicy with a declared egress graph as an
operational invariant, emitted by `platform-app`.

**This cluster runs Flannel, which ships no NetworkPolicy controller.** Verified empirically
on 2026-09-02: a `default-deny` ingress policy in a scratch namespace had *no effect* — the
target pod remained reachable. Every NetworkPolicy in the pre-platform namespaces on that cluster is
therefore decorative and has always been.

## Decision
`platform-app` still emits the policies. They are documented as **not currently enforced**,
in the chart's README and in this ADR, and the fact is not to be quietly forgotten.

## Reasoning
The egress graph is real, hard-won knowledge — it is the actual service dependency graph,
already debugged in the old repo. Expressing it declaratively costs nothing and is correct
the moment a policy-capable CNI exists. Deleting it would lose the knowledge; pretending it
is enforced would be a false security claim in a document someone will later rely on.

Installing Calico policy-only (canal) alongside Flannel was considered and deferred: it
rewrites cluster networking on a single node with no failover, and belongs in its own change
with a tested rollback, not folded into a platform build.

## Consequences
**Do not claim network segmentation in any security review of this platform until a policy
controller is installed.** The isolation that does hold is namespace + RBAC + the Gateway's
`allowedRoutes` selector, plus per-app credentials on shared datastores.
