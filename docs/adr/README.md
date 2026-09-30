# ADRs

Decisions taken during the build, where the cluster or upstream reality differed from the
pre-build design set (`../history/design/`, whose own `adr/0001–0013` are the architecture
this implements). Each names what it amends.

| ADR | Status | Decision |
|---|---|---|
| [0101](0101-no-platform-infra-chart.md) | accepted | Cluster singletons are manifests, not a chart; per-app provisioning is `platform-tenants` |
| [0102](0102-psa-before-kyverno.md) | accepted | PSA first; Kyverno deferred until the audit log says what to mutate |
| [0103](0103-networkpolicy-not-enforced.md) | accepted | **NetworkPolicy is emitted but not enforced** — Flannel has no policy controller |
| [0104](0104-lasuite-charts-from-git.md) | accepted | **La Suite publishes no Helm repository** — charts come from pinned git refs |
| [0105](0105-one-san-certificate-http01.md) | accepted | One SAN certificate over HTTP-01; no DNS-01, no wildcard |
| [0106](0106-datastore-secret-shape.md) | accepted | App-shaped Secret keys from named profiles (`env: lasuite\|find\|calendars\|projects\|messages`) |
| [0107](0107-deps-stops-at-the-namespace-boundary.md) | accepted | `platform-deps` shapes credentials; the platform layer still provisions |
| [0108](0108-upstream-the-charts-we-write.md) | accepted, amended | Charts we write for La Suite apps go upstream — Projects' and Messages' written in the app's repo, consumed from the fork's tag |
| [0109](0109-media-proxy-belongs-to-the-surround.md) | accepted | The `/media` auth-subrequest proxy is a route implementation, so it lives in `platform-app` |
| [0110](0110-object-store-is-published-for-drive.md) | accepted | **The object store is internet-reachable for one bucket** — Drive presigns uploads to the browser |
| [0111](0111-opensearch-security-posture.md) | accepted | **OpenSearch runs with the security plugin on** — the index prefix is the tenant boundary |
| [0112](0112-cluster-services-are-optional-layers.md) | accepted | Gateway, cert-manager and MetalLB are optional Flux layers chosen in `cluster.yaml`; GatewayClass and the address pin are values |
| [0113](0113-media-through-the-gateway.md) | accepted | LiveKit's media goes through the Gateway's L4 listeners; one address per cluster, `livekit.ip` gone |

Superseded from the design set: `0002` (library chart per component) → `0104` and the
three charts in `charts/`; `0012` (upstream La Suite charts) → `0104`; `0013` (Kyverno
invariants) → `0102` and `policy/`. `0003` (Flux, exact pins), `0005` (generate-once
secrets) and `0008` (tenancy labels) still hold and are cited from the code as
`history/design/adr/000x`.
