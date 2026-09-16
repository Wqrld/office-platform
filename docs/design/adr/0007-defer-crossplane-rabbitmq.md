# ADR-0007: Defer Crossplane and RabbitMQ

## Status
Accepted.

## Context
The original proposal's stack includes Crossplane with `provider-keycloak` and `provider-sql`,
and RabbitMQ Cluster Operator plus Messaging Topology Operator, with an external-broker mode.

Against the actual inventory: **nothing in this suite uses AMQP.** Celery, in Docs, Drive and
Find, uses Redis as its broker. And the existing repo already configures the Keycloak realm
declaratively via keycloak-config-cli — 820 lines, ten clients after the cut and the People addition, correct mappers and
scopes, working today.

Every operator installed is an upgrade cycle owned forever. For a platform whose stated goal
is maintainability by a small team, that is the cost that matters.

## Decision
Neither in v1.

RabbitMQ: not built at all. Adding a datastore kind later is additive — the app contract does
not change (P4).

Crossplane: start with realm-as-config applied by a Job on change, and add
`provider-keycloak` only if realm drift becomes an observed problem rather than a predicted
one. `provider-sql` is only needed for external-database provisioning; until an organisation
actually brings its own server, the external mode in `06-datastores.md` consumes an
existing database rather than provisioning one.

This is principle P5 — exceptions have a home; used three times it becomes a feature — applied
to the platform's own dependencies rather than only to application config.

## Consequences
Two fewer operators and one fewer control plane to upgrade. If realm drift does bite, adding
Crossplane later is a platform-layer change that no application file sees.

The risk accepted: realm configuration is reconciled on change rather than continuously, so
manual edits in the Keycloak admin console persist until the next apply. Mitigated by keeping
the realm export in git and by RBAC on the admin console.
