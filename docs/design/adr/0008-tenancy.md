# ADR-0008: Ship single-tenant; keep names tenant-qualified

## Status
Accepted.

## Context
The target is a few organisations, most likely one installation each — single tenancy.
Multi-tenancy is wanted if it is cheap.

None of these applications is tenant-aware. Docs, Drive, Meet and the rest each assume one
Keycloak realm and one user population. Realistic multi-tenancy therefore means
namespace-per-tenant with the full stack replicated and a realm per tenant — not a tenant
column in a shared database.

The existing repo has an optional per-app `namespace`, which is application isolation, not
tenant isolation: one realm, one domain, one `derivePassword` root, no tenant dimension
anywhere.

## Decision
Ship single-tenant. But qualify every resource name, label and hostname with a `${TENANT}`
substitution variable from day one, supplied by each cluster's `vars.yaml`, even while only
one tenant exists.

Multi-tenancy, when wanted, is then one Flux Kustomization per tenant with a different
`${TENANT}` and `${BASE_DOMAIN}` — plus a realm per tenant and a decision about whether
datastores are shared or replicated.

## Consequences
Cost today is one substitution variable and a naming convention. Cost of retrofitting later
is renaming every object in a running platform, which in practice means never.

This does not make the platform multi-tenant, and we should not claim it does. It makes
multi-tenancy a project rather than a rewrite.
