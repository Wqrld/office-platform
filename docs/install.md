# Install

From nothing to the suite serving on your domain, running a published version. Releasing
one is `releasing.md`. Two shapes: a fresh VPS, where the platform installs everything
above Kubernetes itself, and an existing cluster, where it uses what is there.

```sh
git clone <office-platform> && cd office-platform
DOMAIN=office.example.org ACME_EMAIL=ops@example.org ./install.sh --k3s        # fresh VPS
DOMAIN=office.example.org ACME_EMAIL=ops@example.org GATEWAY_IP=10.0.0.5 ./install.sh --existing
```

`install.sh` does the steps below in order and stops at the first that fails. Read on for
what each one needs from you.

## 0. The cluster underneath

**Fresh VPS** (`--k3s`): one machine with a public address, ≥10 cores, fast disk. The
script installs k3s (Flannel, local-path storage, no Traefik, no ServiceLB) and the platform
installs the rest: Envoy Gateway, cert-manager, MetalLB with the node's address as its pool.

**Existing cluster** (`--existing`): a kubeconfig with cluster-admin, and

| Need | Why | Or let the platform install it |
|---|---|---|
| A default StorageClass, or `storageClass` set | Postgres, Valkey, Garage, OpenSearch claim volumes | — |
| Gateway API + a Gateway controller (we run Envoy Gateway) | the one entry point | `cluster.gateway.install: true` |
| cert-manager with `enableGatewayAPI: true` | HTTP-01 is solved through our Gateway; without the flag no certificate ever issues | `cluster.certManager.install: true` |
| A LoadBalancer provider | the Gateway's public address | `cluster.loadBalancer.install: true` (MetalLB, L2) |
| Outbound 587 or 465 | the mail relay; 25 is usually blocked | — |

`cluster.gateway.className` names your GatewayClass (`eg` by default) and
`cluster.loadBalancer.kind: none` means your provider allocates and nothing pins an address —
`gateway.ip` is then the address it gave you. `./preflight.py cluster.yaml` checks all of
this against the live cluster before anything is applied.

## 1. DNS

```sh
./dns.py cluster.yaml            # the records
./dns.py cluster.yaml --check    # what resolves, and what disagrees
```

Every record before the first release, a wildcard is fine. One SAN that fails validation
fails the whole certificate, so one wrong record is an outage for every application. Every
record, `turn.` included, points at the Gateway: it is the one address (adr/0113).

## 2. Your file

`cluster.yaml` is the whole of what you keep: the Flux frame, the platform version, and
your choices. `install.sh` writes it from `examples/cluster.yaml` and your variables;
`charts/control-plane/values.yaml` documents every value and the schema refuses anything
else. Keep it somewhere — re-applying it is the upgrade until it lives in a git
repository or an OCI artifact and the `FluxInstance.spec.sync` block points there
(`examples/cluster.yaml` shows both).

Check it offline, no cluster needed:

```sh
helm template platform charts/control-plane --values <(yq '.spec.values' cluster.yaml) >/dev/null
```

## 3. Secrets you type

Everything else — database roles, cache passwords, OIDC secrets, the Keycloak admin, Garage
keys — is generated in-cluster once. These three come from a provider, so no generator can
make them. `install.sh` creates them before Flux starts when its variables are set.

**Registry** — only for a private registry (`registry.pullSecret`):

```sh
kubectl -n flux-system create secret docker-registry harbor-auth \
  --docker-server=<registry> --docker-username=<robot> --docker-password=<token>
```

**Mail** — `SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM`, `SMTP_TLS=starttls|ssl`.
Without it the platform ships a placeholder relay so every pod starts, and prints
*SMTP not configured — invitations and password reset will not work*. To add it later:
set `smtp: {configured: true}` in `cluster.yaml`, apply, wait for the placeholder to be
pruned, then

```sh
kubectl -n office-data create secret generic smtp-credentials \
  --from-literal=host=smtp.example.net --from-literal=port=587 \
  --from-literal=username='…' --from-literal=password='…' \
  --from-literal=useTLS=true --from-literal=useSSL=false \
  --from-literal=from=noreply@<domain>
# the realm took the placeholder; re-run its Job (platform/identity/README.md, Rotating the relay)
kubectl -n office-identity delete job -l app.kubernetes.io/instance=tenants
flux reconcile helmrelease tenants -n office-data --force
```

then restart what sends: `kubectl -n office-<app> rollout restart deploy` for every app.

**Hugging Face** — `HF_TOKEN`, only for Meet's transcripts. A read token from an account
that has accepted the terms on `pyannote/speaker-diarization-3.1` and
`pyannote/segmentation-3.0`; without it the whisperx pod never becomes Ready and nothing
else about Meet minds. `kubectl -n office-data create secret generic huggingface --from-literal=token=hf_…`.

**Your own S3** — only with `objectStore.mode: external`: a Secret `object-store` in
office-data with `endpoint region accessKeyId secretAccessKey`, buckets `docs drive meet`
made beforehand, and CORS on `drive` allowing `https://drive.<domain>` `GET HEAD PUT`.

## 4. Bootstrap

```sh
kubectl apply -f https://github.com/controlplaneio-fluxcd/flux-operator/releases/download/v0.59.0/install.yaml
kubectl apply -f cluster.yaml
flux get kustomizations --watch
```

From here it is unattended: `cluster-*` → `infra` → `platform` → `objectstore` → one
`app-<name>` per enabled app, each waiting on the last. Expect CNPG, Keycloak and
OpenSearch to take their time.

## 5. Verify

```sh
./dns.py cluster.yaml --check
kubectl -n office-system get certificate office-tls       # Ready=True
kubectl get externalsecret -A | grep -v SecretSynced     # only the header line
DOMAIN=<domain> E2E_USER=<user> E2E_PASSWORD=<password> apps/drive/e2e.py
```

Then users: the realm ships none. `https://id.<domain>`, admin from the
`keycloak-bootstrap-admin` Secret in office-identity. A real login is the test that
matters; the likeliest failure is internal/external OIDC URL divergence, which looks like a
wrong client secret.

First run: `gateway.tlsIssuer: letsencrypt-gateway-staging` proves the chain without
spending rate limit; switch to `letsencrypt-gateway` and delete the `office-tls` Secret.

## Traps

- **`smtp.configured: true` with no Secret** is every backend pod in
  `CreateContainerConfigError`, and nothing in the event says "mail". Deliberate: an
  optional `envFrom` would fall back to `localhost:25` and fail one invitation at a time.
- **Rotating a generate-once Secret** (`refreshInterval: "0"`): delete the owned Secret,
  ESO redraws every key in it, restart what reads it. A live one cannot gain a key.
- **Collabora** needs `CHOWN,FOWNER,MKNOD,SYS_CHROOT` and no `allowPrivilegeEscalation: false`;
  already set. Two startup ERR lines about the jail are expected.
- **Find is title-only** until `docs/reindex-docs.yaml` runs after a restore, silently.
- **Docs' theme is cached in Redis for 24h**; clear `*theme*` in db 1 after changing it.
- `calendars-caldav-initdb` probes `PGDATABASE=postgres`; the role needs CONNECT there.
