# Deferred — routes for decommissioning ingress-nginx

Harbor and the Longhorn UI still resolve to 45.136.141.136 and are served by
ingress-nginx. These manifests move them onto the office Gateway, and were built and
**verified working** on 2026-09-02 (valid certificate, correct backends, allowlist
denying and permitting) before the plan changed to giving the Gateway its own address
instead of taking nginx's.

They are kept because they are the finished half of retiring ingress-nginx.

## To apply them

They may only be applied **together with** the DNS change, because of the certificate
rule below:

1. Add `harbor.mijnbureau.haaijer.dev` and `longhorn.mijnbureau.haaijer.dev` to
   `../certificate.yaml`.
2. Repoint both records to the Gateway's address.
3. `kubectl apply -f .` and label the two namespaces (`../../infra/adopted-namespace-labels.yaml`).
4. Retire ingress-nginx.

Note the Longhorn policy is a **tightening**, not a port: under nginx the Longhorn UI
had no authentication and no source allowlist at all.
