# 0117 — The `office.haaijer.dev/*` label domain stays

**Status:** accepted · **Date:** 2026-10-08

## Context
The platform's own labels carry a personal domain: `office.haaijer.dev/gateway-access` on
every namespace that may attach routes to the shared Gateway (`apps/namespace.yaml`,
`platform/namespace.yaml`, `platform/identity/namespace.yaml`), matched by the Gateway's
`allowedRoutes` selectors (`platform/gateway/gateway.yaml`), and
`office.haaijer.dev/placeholder` on the SMTP placeholder Secret, which `preflight.py` reads.
An organisation installing the platform may reasonably expect a neutral name.

## Decision
Keep it. Renaming is not cleanup: it is a breaking change for every live cluster.

## Reasoning
The Gateway selects namespaces by this label. Changing label and selector in one release
leaves a window in which the old namespaces no longer match and every route detaches, so a
rename has to ship in two releases: first label namespaces with both domains, then switch
the selectors and drop the old label. That is worth doing only together with a reason to
rename — a published distribution under a neutral name — not on its own.

## Consequences
New platform labels use the same domain, so there stays one. If the domain changes, it
changes everywhere above in the two-step order, with a CHANGELOG entry for each step.
