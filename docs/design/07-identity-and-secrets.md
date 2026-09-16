# 07 — Identity and secrets

Two concerns, one file, because in the old repo they are the same mechanism and untangling
them is the single biggest improvement available.

---

## Part 1 — Secrets

### The problem

Every secret in the platform — database passwords, cache passwords, object-store root
credentials, and all OIDC client secrets — derives from one environment variable at
**template-render time**:

```
{{ derivePassword 1 "long" (requiredEnv "MIJNBUREAU_MASTER_PASSWORD") "keycloak" "docs_client_secret" | sha1sum }}
```

It is clever, and it is a trap:

- **No rotation.** You cannot rotate one credential; you rotate the master and therefore
  everything, simultaneously, across every app.
- **The master password must exist wherever templates render** — CI, the GitOps controller's
  environment, and every developer's shell. Its blast radius is the entire platform.
- **`sha1sum` truncation** on client secrets.
- **Secrets are a function of config**, so they land in rendered output and in diffs.

### The replacement

**Generate once, into the cluster. Never derive at render time.**

```
SOPS/age root ──→ bootstrap secrets (ESO credentials, backup keys) ── in git, encrypted
                        │
                  External Secrets Operator
                        │
        ┌───────────────┼────────────────────┐
   generated        provider-held        normalised
   passwords        (Vault / cloud)      datastore secrets
   (ESO generators)                      (ExternalSecret templates)
```

- **Bootstrap roots** — the ESO backend credential, the backup encryption key, the Keycloak
  admin password — are SOPS/age encrypted in `config/secrets/`. These are the only secrets in
  git, and the only thing a disaster recovery needs besides the repo.
- **Everything else is generated in-cluster** by an ESO generator or the owning operator
  (CNPG generates its own role credentials) and reshaped by an `ExternalSecret` `template:`
  block into the canonical key set from `06-datastores.md`.
- **Organisations with an existing secret store** point `secretStoreRef` at it and nothing
  else changes. That is P4 doing its job.

### Migration rule

Do **not** port `derivePassword` "just for now". It is load-bearing in the old repo precisely
because it was convenient at the start, and it will be equally load-bearing here within a
month. The first cluster bootstrap must already be generate-once. See `adr/0005`.

### What stays in git

| In git (SOPS-encrypted) | Never in git |
|---|---|
| ESO backend credential | database passwords |
| Backup encryption key | cache passwords |
| Keycloak admin bootstrap password | OIDC client secrets |
| age recipients in `.sops.yaml` | object-store credentials |

---

## Part 2 — Identity

### Shape

- **Keycloak Operator** runs the instance; its database is a normal `platform-deps`
  Postgres consumer.
- **The realm and its clients are declarative config in git**, applied by a Job on change.
- **Client secrets are generated in-cluster** and read by both Keycloak and the consuming app
  from the same ESO-managed Secret. Neither one holds the source of truth in git.
- Keycloak is a hard `dependsOn` for ten applications and the riskiest recurring upgrade in
  the stack. **Pin it.** Upgrade deliberately in dev. Keep the realm export in git even once
  something else is the source of truth.

Crossplane `provider-keycloak` is deferred, not rejected — `adr/0007`. The old repo's
keycloak-config-cli approach works and is 820 readable lines. Continuous reconciliation of
ten clients is not worth a control plane until drift is an observed problem.

### The clients

Ten: nine surviving the Nextcloud and OpenProject cut, plus People. Harvest the
definitions — mappers, scopes, redirect URIs — from `helmfile/apps/keycloak/keycloak.yaml.gotmpl` in the old repo. They are
correct and they took a long time to get correct.

| Client | App | Notes |
|---|---|---|
| `docs` | Docs | |
| `drive` | Drive | |
| `meet` | Meet | |
| `conversations` | Conversations | |
| `calendars` | Calendars | |
| `find` | Find | |
| `grist` | Grist | |
| `bureaublad` | Bureaublad | portal; needs the widest scopes |
| `people` | People | *M6* |
| `synapse` | Element / Synapse | Matrix delegation via **MAS**, not Synapse's own OIDC; most fragile of the ten |

### Every app does OIDC in-app

This is the fact that shapes the contract. All ten authenticate themselves — the Django apps
via mozilla-django-oidc — with their own sessions and user provisioning. **Do not put edge
OIDC in front of them** (`02-architecture.md` §2).

So one input produces the whole block. `oidc: {client: docs}` in the app's **prerequisites**
release (`05-app-contract.md`) renders a Secret — not values spliced into the app chart, which
a library helper cannot reach — that the upstream chart consumes through `envFrom`:

```
OIDC_OP_JWKS_ENDPOINT, OIDC_OP_AUTHORIZATION_ENDPOINT, OIDC_OP_TOKEN_ENDPOINT,
OIDC_OP_USER_ENDPOINT, OIDC_OP_LOGOUT_ENDPOINT, OIDC_RP_CLIENT_ID, OIDC_RP_CLIENT_SECRET,
OIDC_RP_SIGN_ALGO, OIDC_RP_SCOPES, OIDC_REDIRECT_ALLOWED_HOSTS, OIDC_REDIRECT_REQUIRE_HTTPS,
OIDC_USE_NONCE, OIDC_CREATE_USER, OIDC_STORE_{ACCESS,ID,REFRESH}_TOKEN,
OIDC_USERINFO_FULLNAME_FIELDS, OIDC_USERINFO_SHORTNAME_FIELD, …
```

22 variables in the old repo, hand-written per app. One helper, one input, here. The claim
mapping (`preferred_username`, `name`, `given_name`, `family_name`, `email`, `email_verified`)
is platform-level config, not per-app.

**Not every variable is uniform, and the helper must admit that.** From the old repo:
`OIDC_RP_SCOPES` differs per client, `OIDC_REDIRECT_ALLOWED_HOSTS` is that app's own host,
`OIDC_STORE_REFRESH_TOKEN_KEY` is per-app, and Bureaublad needs the widest scopes. So the
input is `oidc: {client: docs, scopes: [...], extraEnv: {...}}` — small, but not a bare
client name. Transcribe the per-app values from `apps/*/values.yaml.gotmpl` rather than
assuming a shared default, and let the app override any variable the helper emits.

**One name, two consumers.** The app reads the client secret from this Secret; Keycloak must
be configured with the *same* secret. Both read one ESO-managed Secret, and the realm
configuration references it rather than holding a value — which is why the realm apply Job
runs after ESO, not before.

### Internal and external URLs are not the same

Verified the hard way in `lasuite-platform`. Pods do not resolve the browser-facing hostname
the way a browser does, so the OIDC endpoints split in two:

| Purpose | URL |
|---|---|
| Browser redirects — authorize, logout | **external**: `https://id.<domain>/realms/<realm>/…` |
| Backend calls — token, JWKS, introspection | **internal**: `http://keycloak.identity.svc.cluster.local/realms/<realm>/…` |

Keycloak needs `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` to accept requests on the internal URL
while `KC_HOSTNAME` is external.

The `platform.oidc` helper must emit both from one input. Getting it wrong produces a login
that works in the browser and fails at token exchange — a symptom that reads like a
credentials problem and is not.

### Per-secret overrides

`lasuite-platform`'s `getSecret` helper checks a per-id override map before falling back to
derivation. We generate rather than derive (`adr/0005`), but keep the indirection:

```yaml
secretOverrides:
  docs-db: {secretStoreRef: vault, remoteKey: prod/docs/db}
```

It lets one credential move to an organisation's own secret store without migrating all of
them, and it is the mechanism by which "bring your own everything" stays a config change.

### Provider abstraction

Point the issuer at the in-cluster Keycloak by default; allow an override to an external IdP.
Several target organisations already run one, and an OIDC issuer is exactly the kind of
contract that should be swappable (P4). The old repo already models this
(`authentication.oidc.issuer` and friends) — keep that shape, drop the derived secrets.

### Service-to-service

Keycloak client-credentials, not a mesh: each app that needs to call another gets a
service-account client, callers present a JWT, callees validate locally against the JWKS.
Same authorization model as user-facing auth, no sidecars, no mesh upgrade cycle. Plus
default-deny NetworkPolicies.

One quirk to carry over: the Docs↔Find service token is a `sha256sum` truncated to 50
characters. It is not a `sha1sum`, and getting it wrong fails in a way that looks like a
permissions bug.
