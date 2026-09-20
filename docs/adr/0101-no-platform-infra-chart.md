# 0101 — Cluster singletons are manifests, not a chart

**Status:** accepted · **Date:** 2026-09-02 · **Amends:** design set `history/design/04-platform-charts.md`

## Context
The design set specifies four charts, one of them `platform-infra` (~150 lines) holding the
shared Gateway, PriorityClasses and ClusterIssuer.

## Decision
Ship three charts. The singletons live as plain manifests in `platform/gateway/`,
parameterised by Flux `postBuild.substituteFrom` against `cluster-vars`.

## Reasoning
A chart earns its keep by being instantiated more than once. These objects are instantiated
exactly once per cluster and are already parameterised by the substitution mechanism we run
anyway. Templating them buys nothing and costs a release/publish cycle between editing a
Gateway and seeing it.

The Gateway's per-application boilerplate — the thing a chart *would* have solved — is
removed instead by design: a single hostname-less HTTPS listener doing SNI selection over one
SAN certificate. Adding an application touches neither the Gateway nor a chart. See `0105`.

## Consequences
`platform-infra` does not exist. If a second cluster ever needs a materially different
Gateway shape, revisit — the substitution variables are the seam.
