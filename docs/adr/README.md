# ADRs

`0001`–`0013` live in the original design set (`platform-design/adr/`) and are the
architecture this build implements.

`01xx` are decisions taken **during** the build, where the cluster or upstream reality
differed from what the design set assumed. Each names the document it amends or corrects.

| ADR | Decision |
|---|---|
| [0101](0101-no-platform-infra-chart.md) | Cluster singletons are manifests, not a chart |
| [0102](0102-psa-before-kyverno.md) | PSA first; Kyverno deferred until the audit log says what to mutate |
| [0103](0103-networkpolicy-not-enforced.md) | **NetworkPolicy is emitted but not enforced** — Flannel has no policy controller |
| [0104](0104-lasuite-charts-from-git.md) | **La Suite publishes no Helm repository** — charts come from pinned git refs |
| [0105](0105-one-san-certificate-http01.md) | One SAN certificate over HTTP-01; no DNS-01, no wildcard |
| [0106](0106-datastore-secret-shape.md) | Canonical concepts, app-shaped Secret keys, named profiles |
| [0107](0107-deps-stops-at-the-namespace-boundary.md) | `platform-deps` shapes credentials; the platform layer still provisions |
| [0108](0108-upstream-the-charts-we-write.md) | **Charts we write for La Suite apps go upstream** — and must be MIT from commit one |
| [0109](0109-media-proxy-belongs-to-the-surround.md) | The `/media` auth-subrequest proxy is a route implementation, so it lives in `platform-app` |
| [0110](0110-object-store-is-published-for-drive.md) | **The object store is internet-reachable for one bucket** — Drive presigns uploads to the browser |
| [0111](0111-opensearch-security-posture.md) | **OpenSearch runs with the security plugin on** — the index prefix is the tenant boundary |
