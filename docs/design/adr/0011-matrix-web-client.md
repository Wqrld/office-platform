# ADR-0011: Matrix web client

## Status
**Proposed — decide during M8.** Deliberately deferred; it blocks nothing before then.

## Context
Element/Synapse stays in scope and is scheduled late (M8). The existing repo ships
`element-web` as the front end.

Since ADR-0012 we deploy Element's own `matrix-stack` chart, which **bundles Element Web and
Element Admin**. So the default is now "whatever ESS ships", and choosing a different client
means disabling ESS's and adding one — still a Deployment and a route, but no longer free.

There is appetite for a different web client. The homeserver choice (Synapse) and the client
choice are independent — any Matrix client speaks to any homeserver — so this is a swap of
one Deployment plus one HTTPRoute, not an architectural change.

## Options
Web clients suitable for self-hosting alongside Synapse:

| Client | Character | Notes |
|---|---|---|
| **Element Web** | Reference client, most features | The incumbent; heaviest, and the one whose upgrade cadence caused the pain |
| **Cinny** | Clean, modern, minimal | Most commonly cited Element alternative for this use case |
| **Hydrogen** | Ultra-lightweight, broad browser support, offline-capable | Built by the Element team; deliberately minimal feature set |
| **SchildiChat Web** | Element fork, traditional IM layout | Inherits Element's feature set and its upgrade cadence |

Selection criteria for a public-sector digital workplace, in rough priority order: OIDC/SSO
support against our Keycloak realm, accessibility, Dutch localisation, encryption handling
that non-technical civil servants can live with, and maintenance activity.

**OIDC support is the criterion likely to decide it** — check it first for any candidate,
because Matrix clients vary considerably in how well they handle delegated authentication,
and it is a hard requirement here (`07-identity-and-secrets.md`).

## Decision
Deferred to M8. Whichever is chosen, it is a `platform-app` tier-2 release: a static
front end, one route, one config file pointing at the homeserver. The chart work is the same
either way, so this decision does not gate any earlier milestone.

## Consequences
Deciding late is cheap here and the information improves with time. The one thing that must
be decided *early* is unrelated to the client: `matrixDomain` can only be set once at setup
and is permanent (`08-app-inventory.md`).

There is no "not Matrix at all" option hiding here. Conversations is an LLM assistant, not an
instant messenger, so Element is the suite's only team chat — dropping it leaves the platform
with no messaging.

One thing that *does* change the client question: Matrix 2.0 authentication runs through MAS,
so client OIDC behaviour is mediated differently than under the old direct-Synapse setup.
Re-check any non-Element client against MAS rather than against Synapse.
