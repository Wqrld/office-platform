# LiveKit — the SFU behind Meet

`office-livekit`: `livekit` (the server, chart `livekit-server`) and `livekit-egress` (the
recorder, chart `egress`), both from `livekit/livekit-helm` at a pinned commit. Meet is the
only consumer. Design context: docs/app-inventory.md "livekit — the Gateway API exception".

## Where the traffic goes

| What | Address | Why |
|---|---|---|
| Signaling (`wss://livekit.${BASE_DOMAIN}`) | the Gateway, like every app | that is where the certificate is; Meet hands the browser this URL (`LIVEKIT_API_URL`) |
| Media: ICE/UDP 7882, ICE/TCP 7881, TURN/UDP 3478 | the Gateway's L4 listeners, via a TCPRoute and two UDPRoutes (surround.yaml, adr/0113) | Envoy proxies each client session to the pod; the SFU sees a NAT it already expects |
| LiveKit → Meet webhooks, egress → LiveKit | in-cluster Services | nothing in those paths needs to leave the cluster |

DNS: `livekit.${BASE_DOMAIN}` and `turn.${BASE_DOMAIN}` both → Gateway; the wildcard
covers them. `./dns.py prod --check` knows about both.

**No TURN/TLS.** TURN over TLS wants :443, which Envoy terminates for every app; a
`turn.` SAN on a listener LiveKit does not own buys nothing. Clients behind a firewall
that blocks all UDP fall back to ICE/TCP 7881 and nothing else.

## What is done against the charts' grain, and why

All three are `postRenderers` in release.yaml and are the whole reason that file is long.

1. **Config in a Secret.** Both charts render their entire config — Redis password and API
   secret included — into a ConfigMap read as one env var. `secrets.yaml` templates the
   same document from the platform's generated values through ESO, and the env var is
   re-pointed at it. The chart's ConfigMap still renders, from the non-secret values, and
   is unused. Keep the port numbers in release.yaml, secrets.yaml and surround.yaml equal:
   the chart declares container ports from values, the process reads the Secret, and the
   Service is hand-written.
2. **No hostPort, no hostNetwork.** The chart wants `hostNetwork: true` and emits
   `hostPort` even without it; PSA baseline refuses both. The ports list is replaced.
3. **No chart LoadBalancer.** Its modes are cloud-specific; `type: disable` leaves the
   ClusterIP the signaling and media routes point at; surround.yaml adds TURN's.

Chart bump checklist (the commit in `charts/control-plane/templates/sources.yaml` is moved by hand):
render with `tests/binding.py`, then check the livekit Deployment still has `LIVEKIT_CONFIG`
as `env[0]` and the same port names; check egress's `EGRESS_CONFIG_BODY` likewise.

## Credentials

- API key `office` / secret from `meet-service-tokens` (`platform/secrets/service-tokens.yaml`,
  key `livekit`). LiveKit, egress and Meet's backend read the same value; the same pair
  signs the webhooks LiveKit sends Meet.
- Valkey user `livekit` on the broker instance, db 1 (`cache: [broker]` in
  `charts/control-plane/apps.yaml`).
- Egress holds **no S3 credentials**: Meet's backend passes bucket, endpoint and keys in
  each egress request.

## Verifying

```sh
kubectl -n office-system get gateway office -o jsonpath='{.status.listeners[*].name}'   # rtc-tcp rtc-udp turn-udp among them
kubectl -n office-livekit get tcproute,udproute                                        # all Accepted
curl -s https://livekit.${BASE_DOMAIN}                    # OK
kubectl -n office-livekit logs deploy/livekit | head       # "starting LiveKit server", nodeIP ${GATEWAY_IP}
```
In a call, `chrome://webrtc-internals` shows the selected candidate pair against
`${GATEWAY_IP}`, and the Envoy pod's access log a 7882 session per participant; block
UDP 7882 to see it fall back to TURN 3478 then TCP 7881.

## Known limits

- Single replica by design at every size: a UDPRoute to one pod. Scaling out is a
  multi-node LiveKit design, not a profile change.
- Egress runs Chrome even for an audio-only transcript; if it OOMs or Chrome fails to
  start, the first things to look at are `resources.limits.memory` and `/dev/shm` (64 MB
  under CRI-O by default — an `emptyDir` in `Memory` mounted there is the usual fix).
- `terminationGracePeriodSeconds` is an hour on egress on purpose: a recording in flight is
  one someone asked for.
