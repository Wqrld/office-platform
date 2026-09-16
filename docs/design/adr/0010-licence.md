# ADR-0010: Stay EUPL-1.2

## Status
Accepted.

## Context
`mijn-bureau-infra` is licensed EUPL-1.2, which is copyleft. `09-harvest.md` lifts material
from it: the Keycloak realm, the OIDC contract, the egress graph, security-context
exceptions, the Rego policy rules, and documentation including 14 ADRs.

A derived work of EUPL-1.2 material stays EUPL-1.2.

## Decision
The new repositories are EUPL-1.2, with attribution to the original project and its
contributors retained. Copyright notices on harvested files are preserved.

## Consequences
This is a deliberate choice rather than an accident of copy-paste, which matters because the
alternative — writing everything from scratch under a permissive licence — would mean
discarding exactly the material that makes the rebuild affordable.

EUPL-1.2 was chosen by the original project as an invitation for private-sector actors to
use, sell and contribute. That reasoning still applies.

The individual `SPDX-License-Identifier: APACHE-2.0` headers on some chart templates in the
old repo should be checked per file before those files are copied verbatim; they indicate
material that arrived from upstream Bitnami charts, which ADR-0004 removes anyway.
