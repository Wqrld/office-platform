# 0105 — One SAN certificate, solved over HTTP-01 through the Gateway

**Status:** accepted · **Date:** 2026-09-02 · **Amends:** design set `history/design/00-start-here.md` (M1)

## Context
M1 calls for "wildcard or per-host, DNS-01 either way". DNS-01 needs provider API
credentials for the zone. None exist, and a wildcard certificate *requires* DNS-01.

cert-manager here is v1.19.1 with `enableGatewayAPI: true` already set, so its HTTP-01
solver can attach a temporary HTTPRoute to our own Gateway.

## Decision
A single Certificate carrying every platform hostname as a SAN, into one Secret, referenced
once by one hostname-less HTTPS listener that selects by SNI. Solved over HTTP-01:
`letsencrypt-prod` (nginx solver) while the legacy ingress holds the public IP, switching to
`letsencrypt-gateway` (gatewayHTTPRoute solver) once the Gateway owns it.

## Reasoning
Removes an entire requirement — no DNS provider credentials anywhere in the platform, and
nothing to rotate. Adding an application is **one `dnsName` line**; the Gateway listener is
never edited, which is what the per-host-listener alternative would have cost.

## Consequences
- Every hostname is visible in Certificate Transparency logs. A wildcard would not expose
  them. Acceptable: these are public service names.
- Let's Encrypt caps a certificate at 100 SANs, and *any* single hostname failing validation
  fails renewal for **all** of them. Alert on Certificate readiness, not on expiry.
- If DNS-01 credentials ever appear, switching to a wildcard is a one-file change.
