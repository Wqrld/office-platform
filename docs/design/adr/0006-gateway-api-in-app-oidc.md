# ADR-0006: Gateway API only; authentication stays in-app

## Status
Accepted.

## Context
The existing repo supports both Ingress and Gateway API behind a `cluster.routingMode` switch,
carrying 24 Ingress templates (1,329 lines) alongside 22 HTTPRoutes. Calendars was never
migrated and has Ingress only.

Separately, the original proposal justified Envoy Gateway partly on `SecurityPolicy` doing
OIDC at the edge — "no oauth2-proxy sidecar ×10". But all ten OIDC applications authenticate
themselves: the Django apps via mozilla-django-oidc, with their own sessions and user
provisioning (22 `OIDC_*` variables in `apps/docs/values.yaml.gotmpl`). Fronting them with
edge OIDC would double-authenticate.

## Decision
Gateway API only. One shared Gateway per environment in an infra namespace, apps attaching
via HTTPRoute with `allowedRoutes.namespaces.selector`. No Ingress templates in the library.

Authentication stays in-app. The OIDC env block is rendered from a single input
(`oidc: {client: docs}`) into a Secret the app consumes with `envFrom` — a library helper
cannot reach inside an upstream chart's templates (`05-app-contract.md`). Edge `SecurityPolicy` remains available for applications that lack
their own OIDC, but the app contract is not designed around it.

Envoy Gateway is still the implementation of choice — for `SecurityPolicy`, rate limiting and
active maintenance — but on those grounds rather than on edge auth.

## Consequences
Deletes 1,329 lines and the dual-mode branching. Calendars needs net-new routing work rather
than a port.

LiveKit is a documented exception: it needs a UDP port range and TURN on its own domain with
its own certificate, which Gateway API serves poorly. It gets a dedicated
`Service type=LoadBalancer` outside the shared Gateway.

A consumer needing Ingress is a fork, and we would rather know.
