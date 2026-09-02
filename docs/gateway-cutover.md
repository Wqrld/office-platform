# Runbook — moving the public IP from ingress-nginx to the office Gateway

45.136.141.136 is the address `*.haaijer.dev` and `*.mijnbureau.haaijer.dev` resolve to. It
is held by `ingress-nginx-controller`, auto-allocated by MetalLB. The Gateway currently runs
on the spare 45.136.141.168, fully verified.

## What breaks, and what does not

| | |
|---|---|
| **Preserved** | Harbor and the Longhorn UI — both already have HTTPRoutes on the Gateway, verified serving with a valid certificate |
| **Preserved** | Flux's pulls from Harbor — in-cluster, over `10.244.0.0/16`, allowlisted |
| **Lost** | Every legacy `flappie` app's ingress (docs, drive, meet, …). Accepted: the stack is being replaced and Docs' data is backed up |

## Steps

```sh
# 0. rollback data
kubectl get svc -n ingress-nginx ingress-nginx-controller -o yaml > /tmp/nginx-svc-before.yaml

# 1. move nginx off .136 (it keeps serving legacy apps, just at a new address)
kubectl annotate svc -n ingress-nginx ingress-nginx-controller \
  metallb.universe.tf/loadBalancerIPs=45.136.141.154 --overwrite

# 2. give .136 to the Gateway
kubectl patch envoyproxy -n office-system office-gateway --type=merge \
  -p '{"spec":{"provider":{"kubernetes":{"envoyService":{"annotations":
      {"metallb.universe.tf/loadBalancerIPs":"45.136.141.136"}}}}}}'

# 3. verify against real DNS (no --resolve)
curl -sS -o /dev/null -w '%{http_code}\n' https://harbor.mijnbureau.haaijer.dev/

# 4. renewals now solve through the Gateway, not through nginx
#    config/clusters/prod/vars.yaml: TLS_ISSUER -> letsencrypt-gateway
```

## Rollback

Reverse steps 1 and 2. The Gateway returns to .168 and nginx to .136; both keep their
configuration, so recovery is two annotations and about thirty seconds.

## Verify after

- `harbor.mijnbureau.haaijer.dev` **from your own machine, not from the node** — the
  allowlist is source-IP based and a node-local request SNATs to `10.244.0.1`, so it does
  not exercise the same path. A 403 means the allowlist needs your real source address.
- `longhorn.mijnbureau.haaijer.dev` likewise. It gained an allowlist it did not have before.
