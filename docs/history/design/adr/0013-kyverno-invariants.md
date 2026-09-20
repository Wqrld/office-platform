# ADR-0013: Platform invariants live in Kyverno, not in chart templates

## Status
Accepted. Follows from ADR-0012.

## Context
The original design enforced the security baseline, required labels, topology spread and the
PDB guard inside `platform-lib`'s templates. That works only for workloads we template.

After ADR-0012 we template two applications. The other thirteen come from upstream charts,
and the operators, datastores and gateway were never templated by us at all. Template-based
enforcement would now cover a small minority of the pods in the cluster.

## Decision
Platform invariants move to Kyverno, split between mutation and validation.

Pod Security Admission in `restricted` mode is the baseline on every application namespace —
it is free, it is upstream, and it already covers privilege escalation, host namespaces,
capabilities and `runAsNonRoot`. Kyverno covers what PSA cannot express.

**Mutate** — applied to every workload in the cluster, ours or not, and deliberately limited
to settings that are **portable across images**:

- `allowPrivilegeEscalation: false`, `capabilities: drop [ALL]`,
  `seccompProfile: RuntimeDefault`
- Required `app.kubernetes.io/*` labels
- `topologySpreadConstraints` when replicas > 1

**Validate** — deny, or audit-then-deny:

- `runAsNonRoot: true` and a non-zero `runAsUser` are **set by someone** (audit → deny)
- `readOnlyRootFilesystem: true` (audit → deny)
- No `minAvailable` PodDisruptionBudget on a single-replica workload
- Resource requests and limits present (audit first, enforce after M7)
- Images from an allowed registry, pinned by tag or digest, never `latest`

### Why `runAsUser` and `readOnlyRootFilesystem` are validated and not mutated

This is the correction that matters most, and it is a change from the first draft.

The old repo's default is `runAsUser: 1001` with `readOnlyRootFilesystem: true`
(`helmfile/environments/default/security.yaml.gotmpl`). That worked because the workloads
were Bitnami images, which are built for UID 1001, in charts we templated. Neither is true
any more. The pods in this cluster will be Keycloak's, CNPG's, Garage's, OpenSearch's,
Envoy's, ESS's and DINUM's — images built for their own UIDs, several of which write to
paths inside their image.

A cluster-wide mutation setting `runAsUser: 1001` on all of them produces permission-denied
crash loops on first boot of a fresh cluster, in components that have to be up before
anything can be debugged. A cluster-wide `readOnlyRootFilesystem: true` produces the same
failure a little later and less obviously. The exclusion list would not be "Collabora and
CalDAV" — it would grow to most of the platform, at which point the mutation is enforcing
nothing and hiding everything.

So: the **chart's own values** set `runAsUser` and `readOnlyRootFilesystem`, per workload,
where the correct value is knowable; Kyverno **asserts** they were set, in audit first, so
the gaps are a list rather than an outage. This is strictly more visible — "what is in git is
what runs" — for the two settings where the first draft's cost was highest.

Documented exclusions to the *validate* rules, declared once in the policy: Collabora, and
Calendars' CalDAV container (`runAsUser: 33`, writable root filesystem).

### The PDB rule is enforced where the PDB is generated

Validating "no `minAvailable` PDB on a single-replica workload" at admission needs a
cross-resource lookup from the PDB to the workload it selects, and at admission time the
workload may not exist yet. So the primary enforcement is in `platform-app` (it decides
whether to emit a PDB, and always emits `maxUnavailable`) plus a CI check over rendered
output. The Kyverno rule is the backstop for objects that arrive some other way.

## Consequences

**Better coverage than the library chart offered.** The baseline now reaches upstream app
charts, CNPG, Garage, Keycloak, the gateway and the operators. That is the majority of pods,
and previously none of them were covered — for the portable settings. For `runAsUser` and
`readOnlyRootFilesystem` the honest position is that coverage becomes a *tracked gap list*
rather than an enforced default, which is worse on paper and considerably better in a
cluster that boots.

**The honest cost: what is in git is not what runs.** A mutation policy is invisible at the
point of use, and "why does this pod have a securityContext nobody wrote" is a genuinely
confusing question at 2am.

Three mitigations, all required rather than optional:

1. **Render-diff runs `kyverno apply`**, so CI shows post-mutation output. The diff a reviewer
   reads is what the cluster will hold.
2. **Policies are few and boring.** Eight of them, listed above, and only three mutate. Kyverno is a backstop for
   invariants, never a place to hide configuration — the moment app behaviour depends on a
   mutation, it belongs in values.
3. **The `latest`-tag rule is deny, not mutate.** Silently rewriting an image tag would be
   worse than failing.

**Ordering.** Kyverno must reconcile before the workloads it mutates, or the first pods of a
fresh bootstrap escape the baseline. It goes in the `20-infra` Kustomization with
`dependsOn: crds`, and the nightly bootstrap-from-scratch test is what proves it.
