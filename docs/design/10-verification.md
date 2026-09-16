# 10 — Verification

A shared surround chart concentrates risk: one template change touches every app. Everything here
exists to make that concentration safe. Without it, the architecture in `04` is worse than
what we have.

## Where each class of bug is caught

Read this table first. A mechanism that catches nothing another one doesn't is not worth its
maintenance, and a gap here is a bug that reaches production.

| Bug | Caught by | When |
|---|---|---|
| Typo'd values key, silently ignored | `values.schema.json`, `additionalProperties: false` | authoring |
| Our template change breaks the minimal case | golden files | PR (`platform`) |
| Our template change alters every app | render-diff | PR (`config`) |
| Upstream bump renames a Service or label | **binding check** | PR + bump |
| Upstream and surround both emit a PDB | binding check | PR + bump |
| Rendered YAML is not valid for the API server | `kubeconform` | PR |
| Missing resources, floating tag, bad registry, unsafe securityContext | Kyverno (CLI in CI, admission at runtime) | PR + admission |
| A Kyverno rule stopped matching after a rewrite | `kyverno test` fixtures | PR |
| Prod pinned to a moving target | config-repo static rules | PR |
| A credential reached git | secret scanning | pre-commit + PR |
| Wrong Postgres version, missing extension, missing grant | preflight Job | install |
| `dependsOn` ordering wrong; something lives only in a shell history | bootstrap-from-scratch | nightly |
| **An upgrade breaks on immutable fields or duplicate env vars** | **upgrade test** | nightly |
| **OIDC works in the browser and fails at token exchange** | **auth smoke test** | nightly |
| External datastore mode has rotted since M3 | nightly rotation | nightly |
| Backups exist but a restore does not work, or is too slow | restore rehearsal | quarterly |
| Something is broken in production right now | generated PrometheusRules | runtime |

The three in bold are the ones the first draft had no answer for, and they are described
below. They matter disproportionately because **every failure catalogued in
`08-app-inventory.md` is an upgrade failure or an identity failure** — not an install
failure.

## Render-and-diff on every PR

**The highest-value practice here and the one the old repo lacks.** It has lint, render and
Conftest — but no diff against the previous commit.

Render every app, diff against the previous commit, post the result on the PR.
A `platform-lib` bump then shows exactly what changes across every app before it merges.
`flux build kustomization` (which resolves the substitutions and overlays) piped through
`dyff` is sufficient; no extra tooling needed.

Without it, a one-line template change silently drops every PDB and you find out during a
node drain.

**What render-diff does not catch.** Our surround selects into workloads that a different
release created. If an upstream chart bump renames a Service or a component label, *our*
rendered output does not change — so the diff is clean and the routes point at nothing. See
the binding check below. This is the price of `adr/0012` and the one test that pays it.

## Two layers of test

They catch different things and you need both.

| Layer | Repo | Question it answers |
|---|---|---|
| **Golden files** | `platform` | "Did this template change break the minimal case?" |
| **Render-diff** | `config` | "What does bumping the chart do to *these fourteen apps*?" |

Golden cases to commit, at minimum: minimal, full, multi-component (5 workloads),
StatefulSet, external database, single-replica (asserts **no PDB is emitted** — the invariant
most likely to regress silently).

## The binding check

**The test this architecture needs and a chart-per-app architecture did not.**

Render the upstream release and the surround release together, then assert:

- every `components[*].service.name` exists as a Service in the upstream output, on the
  declared port;
- every `components[*].selector` matches at least one pod template in the upstream output;
- the upstream release emits **no** PDB, ServiceMonitor, HPA or NetworkPolicy of its own —
  those are the surround's, and two objects selecting the same pods is a drain that hangs;
- `pdb.enabled` in the surround agrees with the replica count the size profile sets on the
  upstream release.

Ten lines of `yq` over rendered YAML, run per app on every PR and on every upstream bump.
Without it, an upstream rename is a silent outage of routing, alerting and disruption budgets
at once, with a green pipeline.

## Schema validation

`values.schema.json` with `additionalProperties: false` on the modelled keys, checked in CI.
A typo'd values key silently doing nothing is the most common Helm failure mode, and the
schema is the only thing that catches it. Generate the values reference with `helm-docs` so
documentation cannot drift from the schema.

## Policy

Kyverno in **audit mode first**, promoted to enforce once the noise is zero. Backstop for the
invariants in `02-architecture.md`, not a place to hide configuration.

Port the existing rules from `policy/*.rego` (`09-harvest.md`). The ones that matter most:

- every container has resource requests and limits
- images are pinned by tag or digest, from an allowed registry
- required labels present on every object
- `runAsNonRoot`, no privilege escalation, capabilities dropped
- no PDB with `minAvailable` on a single-replica workload

## Bootstrap from scratch, in CI

Empty cluster → full platform with one `flux bootstrap` plus a decryption key, on kind or
vcluster.

This is a maintainability test disguised as a disaster-recovery test. If it passes, nothing
critical lives only in someone's shell history, and the dependency ordering is genuinely
correct rather than accidentally correct. It is also the only honest way to know that the
`dependsOn` graph in `03-repo-layout.md` is right.

Run it nightly, not per-PR — it is slow, and a nightly failure is still fast enough.

## The upgrade test — the one shaped like our actual failures

Bootstrap-from-scratch proves a **fresh install** works. Almost nothing in
`08-app-inventory.md` is a fresh-install failure:

- Find's migrate Job has an immutable `spec.template` and a name that rarely changes — it
  breaks on *upgrade*, and a fresh install never sees it.
- Kubernetes 1.34 rejecting duplicate env vars bit Keycloak and People on *upgrade*.
- Meet's chart version not tracking its app version is a *bump* hazard.
- A Helm rollback reverting code but not a migrated schema only exists on *upgrade*.

So: a second nightly job that installs the **last released pins**, waits for green, then
reconciles to `HEAD` and waits for green again. Same kind cluster, one extra step, and it is
the only test in this document whose shape matches the failures we already know about.

Run the same job on every Renovate bump PR for the app being bumped. That converts "does this
DINUM release upgrade cleanly" from a production question into a CI answer, which is the
practice that makes `adr/0012` safe rather than merely cheap.

## The auth smoke test

The platform's most likely serious bug is not a broken pod. It is described in
`07-identity-and-secrets.md`: internal and external OIDC URLs diverge, **login works in the
browser and fails at token exchange**, and the symptom reads like a credentials problem. No
static check in this document catches it. Neither does bootstrap-from-scratch — every pod is
Ready and the platform does not work.

M2's exit criterion already requires a throwaway client to complete an OIDC login against the
realm. **Keep it as a permanent nightly job rather than a milestone gate**, and extend it as
apps land: a scripted authorization-code flow against Keycloak, then one authenticated API
call per app through the Gateway on its real hostname. A dozen lines of `curl` and `jq` per
app.

Two things it must exercise deliberately, because both are ours and both are silent:

- the **internal** token/JWKS path as the pods use it, not only the browser-facing one;
- the Docs↔Find service token, whose `sha256`-truncated-to-50 shape fails as a permissions
  error when wrong.

## Keep external mode alive after M3

`mode: external` is a first-class mode (`adr/0009`) and M3 proves it once, with Grist. A mode
proven once and never exercised again is a claim, not a feature — and the five things
`06-datastores.md` says break in external mode are exactly the things that rot silently.

Put it in the nightly rotation: the same kind cluster, one app, pointed at a plain Postgres
and a MinIO or SeaweedFS container standing in for someone's S3. Cheap, and it keeps the
contract honest.

## Policy needs its own tests

Six mutation and validation policies enforcing the platform baseline are themselves code, and
a mutation that has quietly stopped matching is invisible — the pods simply come up without
the baseline and nothing fails.

`kyverno test` takes a policy, an input resource and an expected result. Commit a fixture per
rule, both directions: a pod that should be mutated and one that should be skipped, a PDB that
should be denied and one that should pass, plus the documented exclusions (Collabora,
Calendars' CalDAV) asserted as *excluded* rather than assumed.

This is the test that keeps `adr/0013`'s honest cost — "what is in git is not what runs" —
from becoming "nobody knows what runs".

## Static rules on the config repo

Cheap greps that encode decisions already made, so they survive the person who made them.
Each is a few lines of Conftest or `yq` in `config/pr.yaml`:

- **No semver range under `clusters/prod/`** (`adr/0003`). One bad upstream release must not
  reach prod everywhere at once.
- **Every image tag pinned**, separately from its chart version (`adr/0012`).
- **`upgrade.remediation.retries: 0` on every release with a migration Job** — we decided
  this in `04`; nothing else notices if it is dropped.
- **`egressCIDR` present whenever `mode: external`** — the schema enforces it, but assert it
  at the config layer too, because the failure looks like bad credentials.
- **Every datastore declared in an app file appears in the recovery inventory.** Drift between
  "what we run" and "what we back up" is the classic silent gap, and it is a diff of two lists.
- **No secret in git.** `gitleaks` in pre-commit and in CI. `adr/0005` makes this a property
  of the design; make it a property the build enforces.

## Size profiles are rendered, not assumed

The 5-to-5,000 claim rests on three overlays that nothing currently checks. Render all three
for every app in CI and assert the invariants:

- `replicas > 1` ⟹ a PDB exists, with `maxUnavailable`;
- `replicas == 1` ⟹ no PDB (`small` is the case most likely to regress);
- HPA, where enabled, has a `maxReplicas`;
- CNPG instance count and Garage node count match the profile.

This does not prove the platform serves 5,000 people. It proves the profiles still say what
they claim to say, which is the part that rots.

## Rehearse the restore, not the backup

Enumerate what cannot be rebuilt from git, in one file:

- Postgres data (10 databases)
- Object-store contents (Docs, Drive, Grist) — and, per bucket, who owns lifecycle and
  retention: quota, versioning, whether anything ever deletes orphaned objects, and whether
  the application's own retention setting agrees with the bucket's (`06-datastores.md`)
- The OpenSearch index — rebuildable from Postgres, but time it
- The Matrix/Synapse state, if Element stays in scope
- The root decryption keys

Restore into a scratch namespace quarterly and **time it**. Knowing the real RTO beats any
amount of backup configuration. Record backup responsibility per app, because in external
datastore mode it transfers to the operator (`06-datastores.md`).

## Observability is generated, never hand-built

The chart knows the name, port and host, so it emits ServiceMonitor, PrometheusRule (error
rate, latency, restart loop, PDB blocked, certificate expiry) and the dashboard reference
from the same values.

Fifteen hand-maintained dashboards is how monitoring rots — and the old repo has 47,885 lines
of vendored dashboard JSON as evidence.

## Keep a `known-limitations.md`

Borrowed from `lasuite-platform`, which keeps 417 lines of exactly this and is visibly better
for it. One file, in the `config` repo, listing every upstream bug, workaround and
undocumented constraint we are currently living with — each with a link to the upstream
issue or PR and a note on what unblocks it.

It is the cheapest high-value document a platform can keep, for three reasons:

- It stops the same problem being debugged twice by different people.
- It makes upgrade decisions concrete — "does this release close any of our entries?"
- It is the honest answer to "why is this configured so strangely", which otherwise decays
  into folklore and then into a change nobody dares make.

Seed it from the entries already in `08-app-inventory.md` (waffle URLs, Find's
`SECURE_SSL_REDIRECT`, Find's immutable migrate Job, Keycloak backchannel URLs, K8s 1.34
duplicate env vars, ARM64 manifests) and add to it every time something surprises us.

The rule that keeps it useful: **an entry is only removed when the upstream fix is released
and we have upgraded to it**, not when the PR merges.

## Documentation that cannot drift

- `helm-docs` generates the values reference from the schema.
- ADRs capture the *why*. In eighteen months someone will propose adding a service mesh, and
  the difference between a two-hour discussion and a two-week detour is whether the reasoning
  was written down.
- `docs/upgrading.md` gets a section per major chart version, written at release time.

## CI pipeline shape

```
platform/  pr.yaml:      lint → schema → golden → kyverno test → render-diff → policy
platform/  release.yaml: tag → helm push oci://ghcr.io/... → cosign sign
config/    pr.yaml:      flux build → render-diff (all apps) → binding check → static rules
                         → size-profile render → policy (kyverno apply) → kubeconform
                         → gitleaks
config/    bump PR:      + upgrade test for the app being bumped
config/    nightly:      bootstrap-from-scratch → upgrade test → auth smoke test
                         → external-mode rotation
config/    quarterly:    timed restore rehearsal (manual, recorded)
```

Per-PR cost is a few minutes and is all static. Everything that needs a cluster is nightly,
where a failure the next morning is still fast enough.

Keep the commit-message lint and the gitmoji convention from the old repo; both are already
agreed and tooled.
