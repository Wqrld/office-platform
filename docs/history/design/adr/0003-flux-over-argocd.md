# ADR-0003: Flux v2 for delivery

## Status
Accepted.

## Context
The existing repo has no working GitOps. `docs/gitops.md` documents an ArgoCD
`ConfigManagementPlugin` that shells out to `helmfile template`: no per-release drift
detection, no health-gated ordering. Ordering is string-concatenated `needs:` in child
helmfiles, repeated per release per app.

We need: to track an upstream chart version automatically in dev and deliberately in prod;
ordering with health gating (operators before CRs, Keycloak before clients, CNPG before
Databases); SOPS decryption; and variable substitution per cluster.

## Decision
Flux v2. `OCIRepository` with a semver range in dev and an exact tag in prod is literally the
version-flow requirement. Flux `Kustomization` provides `dependsOn` with health checks,
pruning, `postBuild.substituteFrom` and SOPS decryption in one object.

ArgoCD works and would be revisited if a UI for non-platform teams became a hard requirement;
tracking an upstream chart version is clunkier there, and app-of-apps encourages sprawl.

## Consequences
Prod must never point at a semver range — one bad chart release would break the platform
everywhere simultaneously, the exact failure GitOps exists to prevent. Renovate opens the prod
bump as a PR where CI shows the rendered diff across every app.

Flux's `Kustomization` is badly named and is not "using Kustomize" in the meaningful sense.
Kustomize proper is used only as a patch layer: one `overlays/` patch for cross-cutting
environment differences, and `postRenderers` as the per-release escape hatch.
