# Runbook — bootstrap from scratch

Empty VM → the suite serving on your own domain.

**This path has never been run end to end.** `platform-design/10-verification.md` reserves a
nightly bootstrap-from-scratch job precisely so that this document can be trusted; it is not
written yet. Every individual piece below is in daily use, but the sequence has never been
executed as a sequence on an empty cluster — the current one was built incrementally, and
its shell history is not this document. Read it as derived from the config that would be
applied, not as a transcript.

Every step is labelled **Required** or **Optional**. Optional means the platform comes up
and serves without it.

---

## 0. The cluster underneath — Required, and not in these repos

None of this is installed by `config/`. It is assumed present, and a missing piece fails
late and indirectly — usually as a Kustomization that never reports Ready.

| Component | Why it is required | What we run |
|---|---|---|
| Kubernetes + a CRI | — | 1.34.2, CRI-O |
| A CNI | — | Flannel. It enforces **no** NetworkPolicy (adr/0103), so `platform-app`'s policies are declarative only |
| A default StorageClass matching `STORAGE_CLASS` | Postgres, Valkey, Garage and OpenSearch all claim volumes | Longhorn |
| A LoadBalancer that honours `metallb.universe.tf/loadBalancerIPs` | `platform/gateway/envoyproxy.yaml` pins the Gateway to `${GATEWAY_IP}` with that annotation. Another provider ignores it and the address is whatever it allocates | MetalLB |
| Gateway API CRDs + Envoy Gateway, GatewayClass **`eg`** | `platform/gateway/gateway.yaml` names that class | Envoy Gateway v1.7.0 |
| cert-manager, with the controller's **`enableGatewayAPI: true`** | The ClusterIssuer solves HTTP-01 by attaching a temporary HTTPRoute to our own Gateway. Without the flag the challenge never routes and the certificate never issues | — |
| An OCI registry you can push to | Charts and config are delivered as OCI artifacts, not files | Harbor |
| Sizing | The legacy stack alone held 3829m; plan ≥10 cores and fast disk | 1 node |

Optional here: Prometheus operator CRDs (nothing in `apps/` enables a ServiceMonitor today),
and anything under `platform/gateway/deferred/` — routes for services this platform did not
create.

## 1. DNS — Required, and first

```sh
./dns.py prod            # the records
./dns.py prod --check    # what already resolves, and what disagrees
```

Create every record it prints **before** step 3. cert-manager solves HTTP-01 through this
Gateway, so :80 and :443 must reach it from the internet, and Let's Encrypt fails the *whole*
certificate if a single SAN fails validation — one mispointed record is an outage for every
application, not for one. A wildcard is fine and is what the script suggests.

Your registry's own hostname must resolve too, or the FluxInstance simply never syncs.

## 2. Point the repos at your world — Required

```sh
git clone <config> && git clone <helm-charts>     # side by side: tests render ../helm-charts
```

| File | Change |
|---|---|
| `clusters/prod/vars.yaml` | `BASE_DOMAIN`, `GATEWAY_IP`, `STORAGE_CLASS`, `TENANT`, `TLS_ISSUER` |
| `platform/gateway/clusterissuer.yaml` | the ACME contact address |
| `release.sh`, `../helm-charts/scripts/publish.sh` | `REGISTRY` / `REPO` |
| `clusters/prod/{sources,config-source,flux-instance}.yaml` | the same registry, in every `url:` |
| `platform/identity/realm.yaml` | the five users are ours. Replace them, or delete the block and create users in Keycloak later |
| `platform/identity/realm.yaml` | `smtpServer.fromDisplayName` is the name recipients see on password-reset mail. Everything else about the relay comes from the Secret in step 4b |
| `~/.harbor-robot` | line 1 username, line 2 password (`HARBOR_ROBOT_FILE` overrides the path) |

Then, offline and without a cluster:

```sh
./tests/build.sh && ./tests/kubeconform.sh && conftest test --policy policy --parser yaml \
  --all-namespaces apps/ platform/ clusters/ infra/
```

`build.sh` is the one that catches a typo'd `${BASE_DOMIAN}` — Flux would leave it in place
and the app would serve a hostname that resolves for nobody.

## 3. Publish — Required

```sh
../helm-charts/scripts/publish.sh 0.2.6    # bumps Chart.yaml and pushes all three charts
./release.sh 1.6.0                          # pushes :1.6.0, repoints the pointer, pushes :latest
git commit -am 'release 1.6.0'              # release.sh leaves the rewritten pointer behind
```

Release from a clean tree. A dirty tree is stamped `-dirty` in the artifact revision and that
version can never be traced back to a commit. The chart version in `clusters/prod/sources.yaml`
and the one you publish must match.

## 4. Bootstrap Flux — Required. Four commands, and the only objects ever applied by hand

```sh
kubectl create namespace flux-system
kubectl -n flux-system create secret docker-registry harbor-auth \
  --docker-server=<registry> --docker-username=<robot> --docker-password=<token>
# flux-operator 0.59.0 — install per its own documentation; it is not vendored here
kubectl apply -f clusters/prod/flux-instance.yaml
```

`harbor-auth` is referenced by the FluxInstance, the config `OCIRepository` and both chart
repositories, and is created by nothing in this repo.

From here it is unattended: the FluxInstance installs Flux, syncs `clusters/prod` from
`:latest`, and drives `20-infra` → `30-platform` → `40-apps`, each waiting on the previous.
Every other secret — database roles, Valkey passwords, OIDC client secrets, the Keycloak
bootstrap admin, the realm user passwords, Garage keys — is generated in-cluster, once.

## 4b. The relay account — Required, and it has an order

`harbor-auth` used to be the only credential you type. **SMTP is the second**, and for the
same reason: a mail account is issued by a provider, so no generator can produce it.

```sh
kubectl -n office-data create secret generic smtp-credentials \
  --from-literal=host=smtp.example.net \
  --from-literal=port=587 \
  --from-literal=username='...' \
  --from-literal=password='...' \
  --from-literal=useTLS=true \
  --from-literal=useSSL=false \
  --from-literal=from=noreply@<your domain>
```

Everything about the relay lives here — host and port included — so switching provider is
this one command and nothing about mail is in git. `useTLS` is STARTTLS and `useSSL` is
implicit TLS; they are mutually exclusive. **587 or 465, never 25**: outbound TCP 25 is
blocked from this host by the provider (measured; 53, 443 and 587 all connect).

The order: `office-data` is created by `30-platform`, and `40-apps` will not settle without
this Secret, so apply it while `30-platform` is coming up. `kubectl create namespace
office-data` first is fine — Flux adopts the namespace and adds its own labels.

Four ExternalSecrets read it back: one per application namespace through `platform-deps`
(`smtp: {enabled: true}` in each app's `deps.yaml`), and `platform/identity/smtp.yaml` for
Keycloak. Nothing else ever sees the office-data copy.

**To rotate it**, edit this Secret, then push it through both hops — a synced Secret alone
changes nothing, because `envFrom` is read once, at pod start:

```sh
for ns in office-docs office-drive office-calendars office-identity; do
  kubectl -n $ns annotate externalsecret --all force-sync=$(date +%s) --overwrite
done
kubectl -n office-docs rollout restart deploy      # and drive, calendars — backends only
platform/identity/set-smtp.sh                      # Keycloak keeps its own copy of the realm
```

```sh
flux get kustomizations --watch      # four objects, all Ready
```

Expect this to take a while: CNPG, Keycloak and OpenSearch each initialise before the layer
above them starts, and `disableWaitForJobs` means Flux reports Ready before migrations finish.

## 5. After the layers are green — Required

- **Realm clients**: on a *fresh* cluster the import creates the realm, its four clients and
  the users from `realm.yaml`, so there is nothing to do. `platform/identity/add-client.sh`
  is for adding a client to a realm that is **already** imported — the import is import-once
  and editing `realm.yaml` afterwards does nothing. Read `platform/identity/README.md`.
- **Realm SMTP**: `platform/identity/set-smtp.sh`. On a *fresh* cluster the import already
  read `smtpServer` out of `realm.yaml`, so this is a no-op — but it is the only way to
  configure mail on a realm that already exists, for the same import-once reason as
  `add-client.sh`. Verify with **Realm settings → Email → Test connection**, then a real
  "Forgot password?" as a realm user.
- **Watch the init Jobs**, `calendars-caldav-initdb` above all: it opens `PGDATABASE=postgres`
  to probe for its database, so the role needs CONNECT there. First install is where that
  shows up.
- **Verify** — the point of a bootstrap you cannot otherwise trust:

```sh
./dns.py prod --check          # every name on the certificate, resolving to the Gateway
kubectl -n office-system get certificate office-tls    # Ready=True; one SAN failure fails all
apps/drive/check-secrets.sh    # the post-renderer attached all ten workloads

E2E_USER=<user> E2E_PASSWORD=$(kubectl -n office-identity get secret realm-user-passwords \
  -o jsonpath='{.data.<user>}' | base64 -d) apps/drive/e2e.py
                               # login, presigned upload, media proxy, WOPI, editing websocket
```

A real login through Keycloak is the test that matters. The failure this platform is most
likely to have is internal/external OIDC URL divergence, which looks exactly like a wrong
client secret (`KC_HOSTNAME_BACKCHANNEL_DYNAMIC`, `07-identity-and-secrets.md`).

## 6. Optional

| Step | When |
|---|---|
| `TLS_ISSUER: letsencrypt-gateway-staging` for the first run | Proves the chain without spending rate limit on a hostname that has never validated. Switch to the real issuer and delete the `office-tls` Secret to reissue |
| Restore legacy data | Only if migrating. `backups/<stamp>/MANIFEST.md` — the PG dump **and** the objects; neither is useful alone |
| `apps/docs/reindex.yaml` | Only after a restore, or after an OpenSearch rebuild. Indexing is driven by `post_save`, so restored documents are invisible to search until this backfills them. Applied by hand on purpose — it depends on Find being up, and a failed Job inside `40-apps` stalls the whole layer |
| `platform/gateway/deferred/` | Only when retiring an existing ingress controller that still holds the public IP — see `gateway-cutover.md` |
| `clusters/demo` | A second cluster on its own domain and its own address. Same four commands |
| Prometheus operator | Nothing enables a ServiceMonitor yet |

## 7. Traps a first install actually hits

Each of these cost a day once. All are already fixed in the config — they are here so the
symptom is recognisable, not so you can act on them.

- **Collabora** needs `CHOWN,FOWNER,MKNOD,SYS_CHROOT` added back, and
  `allowPrivilegeEscalation: false` deliberately left off — no_new_privs makes the kernel
  ignore the file capabilities `coolforkit-caps` carries, which breaks it the same way a
  missing capability does. The stock image dies with `Failed to spawn coolforkit`. Two
  startup ERR lines about the jail falling back to copy are expected.
- **The WOPI configuration lives in an evicting cache.** On a miss, Drive calls every
  document an unsupported format and does not self-heal. A refresh CronJob runs every ten
  minutes.
- **Docs' theme JSON is cached in Redis for 24h** — a changed ConfigMap is not enough; clear
  `*theme*` in db 1.
- **Find returns title-only results** until the reindex runs, and reports no error.
- **A missing `smtp-credentials` is every backend pod in `CreateContainerConfigError`**,
  with nothing in the event about mail. `envFrom` is deliberately not `optional: true`:
  optional would start the pod and fall back to the upstream default of SMTP against
  `localhost:25`, so every invitation would fail at send time instead, one at a time.
- **A generate-once ExternalSecret cannot gain a key later.** `refreshInterval: "0"` means
  written once, not "re-draw when the spec changes". Adding a key to a live one silently
  never appears; forcing it rotates every other consumer's password.
- **Imported users get no roles unless `realmRoles` says so.** Login works everywhere and
  the account console 401s with no server-side error event.
