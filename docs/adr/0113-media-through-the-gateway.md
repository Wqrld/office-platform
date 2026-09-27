# 0113 — LiveKit's media goes through the Gateway: one address per cluster

**Status:** accepted · **Date:** 2026-09-21 · **Amends:** `0101`, `apps/livekit/README.md`

## Context
Meet needed a second LoadBalancer address, `livekit.ip`: WebRTC media is UDP and ICE, and
the assumption was that an L7 proxy cannot carry it. A VPS has one address, so Meet was
unavailable on half the installs; on the other half, two addresses meant two pins in
`cluster.yaml`, a MetalLB-only annotation on a second Service, and a `turn.` record that had
to beat the wildcard. MetalLB's IP sharing was the obvious fix and does not apply: it needs
both Services on `externalTrafficPolicy: Cluster`, which costs every app its client address.

## Decision
The Gateway carries the media. Three L4 listeners on it — 7881/TCP, 7882/UDP, 3478/UDP —
and a TCPRoute and two UDPRoutes in `apps/livekit/surround.yaml`. LiveKit advertises
`${GATEWAY_IP}`. `livekit.ip` no longer exists; the Gateway is the one LoadBalancer.

## Reasoning
Envoy's UDP proxy opens one upstream socket per client session, so the SFU sees a stable
NAT'd 5-tuple per client — the same thing it sees behind any cloud LB — and ICE completes.
Tested on prod, 2026-09-21: two participants on different networks, 11 MB and 4 MB of
media through 7882, both connected within 500 ms, Envoy at 69m CPU beside LiveKit's 95m.
Envoy's 60 s UDP idle timeout never touches a media flow; it closes STUN probes, correctly.

This is provider-independent — MetalLB, k3s ServiceLB, any cloud — where sharing an
address is MetalLB-specific and `hostPort` is refused by PSA baseline.

## Consequences
- One address, one pin, one `A` wildcard. `install.sh` needs nothing extra for Meet.
- Media transits Envoy: one hop, a fraction of the SFU's own CPU. A single Envoy replica
  is already the platform's single point of entry, so this adds no new one.
- The three ports are open on the Gateway address with Meet off; they connect to nothing.
- TURN/TLS is still not offered (`apps/livekit/README.md`).
