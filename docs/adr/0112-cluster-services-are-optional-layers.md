# 0112 — Cluster services are optional Flux layers, chosen in `cluster.yaml`

**Status:** accepted · **Date:** 2026-09-21 · **Amends:** `0101`, `docs/install.md` §0

## Context
Half of the installs are fresh single-node VPSes, half are existing clusters. The old
bootstrap assumed Envoy Gateway, cert-manager (with `enableGatewayAPI`) and MetalLB were
already there, hardcoded the GatewayClass `eg` and MetalLB's annotation, and left a missing
piece to fail late as a Kustomization that never reports Ready. On a VPS that is most of
the work; on an existing cluster the hardcoded names are usually wrong.

## Decision
The control plane grows a `cluster:` block. `cluster.gateway.install`, `cluster.certManager.install`
and `cluster.loadBalancer.install` each add a Flux layer that installs that service; off, the
platform assumes it and `preflight.py` checks it. `cluster.gateway.className` and
`cluster.loadBalancer.kind` (`metallb` | `none`) parameterise what was hardcoded: the
GatewayClass by substitution, the address pin as a whole-map `${LB_ANNOTATIONS}` that is
`{}` when the cluster's own provider allocates.

Envoy Gateway and MetalLB are `cluster-<service>` (the chart) and `cluster-<service>-config`
(GatewayClass, IPAddressPool) — two layers each, because a CR cannot be applied before the
chart that brings its CRD. cert-manager is a kustomize component of `infra` that also makes
the Garage operator wait for it. Every layer is plain manifests under `cluster/`, like
`infra/`; the chart only decides which are emitted.

## Reasoning
Layers and components are what the control plane already emits, so nothing new has to be
learned to read it: a service is a directory, choosing it is a value, and `tests/build.py`
builds the result the way the cluster will. A `platform-infra` chart (rejected in `0101`)
would have to be published to change a pin; these change like any other `infra/` file.

## Consequences
- `install: false` everywhere is the pre-0112 cluster, byte for byte except the
  annotation's spelling. Prod and demo stay that way.
- Switching a service off after it is installed leaves it running: the layer Kustomization
  is `keep`, like every other, so a bad edit cannot prune the Gateway the platform runs on.
  Removing it is a deliberate `flux delete ks`.
