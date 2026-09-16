# 0111 — OpenSearch runs with the security plugin on

**Status:** accepted · **Date:** 2026-09-06 · **Decides:** design set `06-datastores.md`
(deferred at M6)

## Context
`06-datastores.md` defers the OpenSearch security posture to the milestone that first needs
the server. That is M6 — full-text search from Docs through Find — so it is decided here.

The reference deployment we work from runs `DISABLE_SECURITY_PLUGIN=true` and plain HTTP,
with the comment "safe for internal-only OpenSearch instances". That is not true on this
cluster. Flannel enforces no NetworkPolicy (`adr/0103`), so *any* pod in *any* namespace can
reach `opensearch-cluster-master:9200`. With the plugin off there is no authentication at
all: every document in every index is world-readable and world-writable from anywhere in the
cluster.

The same argument already settled the Valkey ACLs (`platform/valkey/README.md`): where
the network enforces nothing, the datastore's own auth is not defence in depth, it is the
only defence.

## Decision
The security plugin is **on**:

1. An internal user per consuming app — today only `find` — with a role granting
   `indices_all` on that app's index pattern (`find-*`) and nothing else.
2. **TLS on the REST layer**, from a self-signed CA private to this cluster
   (`platform/opensearch/certificate.yaml`). The Let's Encrypt ClusterIssuer issues
   for public names and cannot sign a `.svc.cluster.local`.
3. **No `admin` internal user.** Cluster administration is the admin certificate only, so
   there is no all-access password anywhere to leak.
4. The **index prefix is the tenant boundary**, and it is enforced server-side by the role
   rather than by a request parameter. `platform-deps`' `opensearch` kind emits the same
   prefix into the app's environment, so the two cannot disagree silently.

## Reasoning
The cost is one CA, one Secret of security config, and the operational wrinkle in
`platform/opensearch/README.md` that changing that config after first boot needs
`securityadmin.sh`. The cost of the alternative is a datastore with no authentication on a
cluster with no network policy, holding the full text of every document in Docs.

Point 4 is the part worth being explicit about. Find's own model already resolves the target
index from the authenticated identity and never from user input — the write path from
`request.auth.index_name`, the read path from the introspected audience. Scoping the
OpenSearch role to the same prefix means a compromised *application* still cannot read
another app's index, not just a compromised request.

## Consequences

**What this does not buy.** Find hardcodes `verify_certs=False`
(`core/services/opensearch.py:41`) and exposes no CA setting. So the REST connection is
encrypted but the server is **never authenticated** — this stops passive reading of index
traffic, and does not stop an active attacker who can get in the path. Closing that needs an
upstream `OPENSEARCH_CA_CERTS` setting; it is worth a PR and is recorded as the follow-up in
`apps/find/README.md`.

**Rotation is manual.** `allow_default_init_securityindex` seeds `.opendistro_security` from
the mounted files on first boot only. After that the index is the source of truth, so
rotating the `find` password means re-rendering the Secret *and* running `securityadmin.sh`
with the admin certificate. The runbook is in `platform/opensearch/README.md`.

**Adding a consumer is three edits**, the same shape as adding a Valkey user: a
generate-once password, a role and mapping in the security config, and the app's
`opensearch:` block. If a third consumer makes that annoying, the fix is a per-user CRD, not
a second cluster.
