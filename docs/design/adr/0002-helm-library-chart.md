# ADR-0002: A Helm library chart is the unit of reuse

## Status
**Amended by ADR-0012.** Its reasoning holds; its conclusion does not survive the discovery
that DINUM maintains charts for most of our applications. The library chart survives at ~250
lines serving four consumers rather than as the centre of the design.

## Context
Nine of fifteen applications have more than one workload; Docs has five. The existing repo
writes a separate template per component per resource kind: 21 PDB files (603 lines), 23 HPAs
(955), 10 VPAs (441), 57 Services (2,540), 35 NetworkPolicies (2,523), 22 HTTPRoutes (784),
24 Ingresses (1,329). Inspection confirms these are semantically identical — `docs/backend-pdb.yaml`,
`meet/pdb-backend.yaml` and `grist/pdb.yaml` differ only in the values path and the component
label.

The original proposal centred on a single `platform-app` chart handling 80% of apps in ~25
lines. Against this inventory that does not hold: five apps have 3–5 workloads and multiple
routes, and would need their own charts regardless.

## Decision
*(Superseded in part by ADR-0012 — recorded as written, because the alternatives it rejected
still stand.)*

`platform-lib`, a Helm library chart, is the deliverable. Its unit is a **component**, not an
application: every helper takes `(root, component name, component values)` and an application
is a map of components. `platform-app` is a thin wrapper for single-shape apps. Applications
with a different shape get their own ~40–80 line chart depending on `platform-lib` — the
normal case here, not the exception.

Alternatives considered: Timoni/CUE (genuinely better at list merging and cross-field
validation, rejected on project risk — pre-1.0 after three years, effectively one maintainer);
KCL (thin adoption, a new language); Kustomize as the composition layer (fifteen apps ×
four environments × a dozen resources, no schema, silent no-op patches).

## Consequences
*(As written. ADR-0012 replaces the mechanism: upstream absorbed the collapse, and
`platform-lib` shrinks to ~250 lines serving four consumers.)*

The collapse is ~16,000 lines into ~1,500, and it is delivered by the helpers rather than by
a single shared app chart — so it survives the fact that most of our apps are structurally
different.

Risk concentrates: one template change touches every application. This is why
`10-verification.md` mandates render-diff on every PR and golden files in `platform`, and why
neither is optional.
