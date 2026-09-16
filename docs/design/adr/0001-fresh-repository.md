# ADR-0001: Rebuild in fresh repositories rather than refactor

## Status
Accepted.

## Context
`mijn-bureau-infra` is unmaintained upstream, built on Bitnami charts that moved to an
unmaintained legacy repository in August 2025, and structured around helmfile with
per-release values files. Measured: 105,167 authored lines for the fifteen applications we
keep, of which 56,996 are copies of Bitnami `values.yaml` — 3% of those lines contain a
template expression and 68% are upstream comments. Two apps' Redis values files differ by
78 lines out of 2,326.

Four properties are structural rather than incidental: Bitnami's `common` library chart is a
build dependency of all 23 authored charts and their template idiom; helmfile has no
library-chart layer, so values duplication is unavoidable; the config tree re-models
Kubernetes APIs across 23 files keyed app-then-component; and there is no GitOps path —
Flux does not support helmfile, and the documented ArgoCD plugin shells out to
`helmfile template` with no per-release drift detection.

## Decision
Start a fresh `platform` and `config` repository pair. Harvest the Keycloak realm, OIDC
contract, network egress graph, security-context exceptions, policy rules and per-app
integration facts. Do not carry the structure, the Bitnami values copies, `derivePassword`,
or the `environments/default/` shape.

## Consequences
Marginal cost of adding an application falls from 6,000–9,000 lines across ~15 files to
25–70 lines in one file. Total authored surface falls to roughly 4,000 lines of config plus
~1,600 of platform charts and policy.

(These figures are the post-ADR-0012 ones. An earlier version of this ADR said "150–400 lines
across 2" and "roughly 13,000 lines" — correct for the world where we authored a chart per
application, which ADR-0012 removed.)

The cost is real: the existing installation is not migrated incrementally, and roughly 37,800
lines of working chart templates are read as reference rather than reused. `08-app-inventory.md`
is deliberately explicit about which applications are expensive.

A cleanup-in-place would recover about 60% of the line count — dropping two apps and dropping
Bitnami — without addressing any of the four structural properties, and would barely move the
marginal-cost-per-app number.
