# ADR-0005: Generate secrets once into the cluster; never derive at render time

## Status
Accepted.

## Context
Every secret in the existing platform — database and cache passwords, object-store root
credentials, all OIDC client secrets — derives from one environment variable at template
render time via `derivePassword ... | sha1sum`.

Consequences in practice: no credential can be rotated independently, only the master and
therefore everything at once; the master password must exist wherever templates render (CI,
the GitOps controller's environment, every developer's shell), giving it a blast radius equal
to the platform; client secrets are `sha1sum`-truncated; and secrets are a pure function of
config, so they appear in rendered output and diffs.

## Decision
External Secrets Operator, with SOPS/age holding only the bootstrap roots. Credentials are
generated once in-cluster — by an ESO generator, or by the owning operator, as CNPG does for
its roles — and reshaped by an `ExternalSecret` `template:` block into the canonical key set
in `06-datastores.md`.

The only secrets in git are SOPS-encrypted bootstrap roots: the ESO backend credential, the
backup encryption key, the Keycloak admin bootstrap password.

Do **not** port `derivePassword` as an interim measure. It is load-bearing in the existing
repo precisely because it was convenient at the start; it would be equally load-bearing here
within a month. The first cluster bootstrap must already be generate-once.

## Consequences
Individual rotation becomes possible. Rendering no longer requires any secret, so CI and
developer machines hold nothing.

Organisations with an existing secret store point `secretStoreRef` at it and nothing else
changes — the same P4 contract that makes bring-your-own-database work. In exchange, ESO
becomes a hard bootstrap dependency, and disaster recovery needs the repo plus exactly one
age key.
