# Identity — Keycloak

Operator and server are one release. `operator/` is a verbatim copy of
`keycloak/keycloak-k8s-resources` at **26.7.3**; everything we change about it is in
`operator/kustomization.yaml`. To upgrade: re-download all five files at the new tag in
one commit, diff, and bump nothing else — the CRDs and the server version move together.

The operator watches only its own namespace (`JOSDK_WATCH_CURRENT`), so it and the
`Keycloak` CR must share one.

## The realm import is import-once. This is not a bug you can configure away.

The operator runs `kc.sh import --file … --override=false`, hardcoded, and refuses to
recreate a Job it has already run. So:

- **Editing `realm.yaml` and reconciling does nothing.** The Job logs
  `Realm 'office' already exists. Import skipped`, and the CR still reports `Done=True`.
- To actually apply a change: delete the realm (admin API `DELETE /admin/realms/office`),
  then `kubectl -n office-identity delete job office`. The operator recreates the Job and
  the realm is imported clean.
- Deleting the realm re-issues every user's `sub`. That is survivable here only because
  Docs matches a login by `sub` and then falls back to email
  (`OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION`). An application without that fallback
  would lose the link between its users and the IdP.

Treat the realm as bootstrap, not as continuously reconciled config. If drift becomes a
real problem, the 26.7 `KeycloakOIDCClient` CRD reconciles a single client continuously
and takes its secret from a `secretRef` — that is the upgrade path for the client half.

## Imported users get no roles unless you say so

A realm import takes each user representation **literally**. An absent `realmRoles` key
means *no roles*, not "the realm's defaults" — `default-roles-<realm>` is applied only to
users created through registration or the admin API. Every user in `realm.yaml` therefore
carries an explicit:

```yaml
realmRoles: [default-roles-office]
```

Without it the symptom is narrow and misleading. Login works everywhere, because Docs
reads the ID token and never inspects roles. But the access token has no `aud: account`
and an empty `resource_access`, so every `/realms/office/account/*` REST call returns
401 and the Account Console renders its generic **"Something went wrong"** page — with no
server-side error event to find, since a 401 there is not an auth *failure*, it is a
missing authorization.

To repair a realm that was already imported without it, grant the role rather than
reimporting — deleting the realm would re-issue every `sub`:

```
POST /admin/realms/office/users/<id>/role-mappings/realm
[{"id": "<default-roles-office id>", "name": "default-roles-office", ...}]
```

## Adding a client to a realm that is already imported

Same consequence as above, in the direction you will actually hit: **adding a client to
`realm.yaml` does not create it.** `realm.yaml` stays the source of truth so a clean
reimport produces the right realm, but on this cluster the realm already exists, so the
client has to be created once through the admin API:

```sh
./add-client.sh drive
```

That script reads the client out of `realm.yaml` itself — so the live realm and git cannot
disagree about anything but timing — resolves `${BASE_DOMAIN}` and the
`$${CLIENT_SECRET_*}` placeholder from the cluster, and POSTs it. It refuses to touch a
client that already exists, so re-running it is safe and it can never rewrite one that was
changed by hand.

Confirm afterwards that the client's secret equals the value in `oidc-client-<name>`. A
mismatch there fails at token exchange and reads exactly like a wrong OIDC configuration.

The 26.7 `KeycloakOIDCClient` CRD was considered for this and rejected: it has no field for
the backchannel/frontchannel logout attributes, and the client id comes from
`metadata.name`. Reconciling a client continuously is worth having, but not at the cost of
silently dropping single-logout.

## Placeholder syntax

Two forms look right and are not:

| Written | Result |
|---|---|
| `$(env:NAME)` | keycloak-config-cli syntax. Keycloak stores the literal string as the secret. Every login then fails with "invalid username or password" while the admin console shows a perfectly normal client. |
| `${NAME}` | Correct for Keycloak — but it is also Flux's `postBuild` substitution syntax, so Flux blanks it first. |
| `$${NAME}` | **Correct here.** Flux emits a literal `${NAME}`; `${BASE_DOMAIN}` in the same file still substitutes normally. |

## Internal vs external URLs

`hostname.backchannelDynamic: true` is the whole mechanism. Verified on this cluster:

```
$ curl https://id.haaijer.dev/realms/office/.well-known/openid-configuration
  issuer                 https://id.haaijer.dev/realms/office
  authorization_endpoint https://id.haaijer.dev/...

$ curl http://keycloak-service.office-identity.svc:8080/realms/office/.well-known/…
  issuer                 https://id.haaijer.dev/realms/office
  token_endpoint         http://keycloak-service.office-identity.svc:8080/...
```

Applications must consume both halves: browser endpoints external, backend endpoints
internal. `apps/docs/secrets.yaml` is the worked example.

## Admin access

`bootstrapAdmin.user.secret` only applies the first time a Keycloak starts against an
empty database. On this cluster the CR was created before that stanza existed, so the
operator generated its own `keycloak-initial-admin` — and deleted it when the stanza
appeared, stranding the account. Recovery, should it happen again:

```
kubectl -n office-identity exec keycloak-0 -- \
  env KC_HTTP_PORT=8123 KC_HTTP_MANAGEMENT_PORT=9123 \
  /opt/keycloak/bin/kc.sh bootstrap-admin user --username tempadmin \
    --password:env KC_BOOTSTRAP_ADMIN_PASSWORD --no-prompt
```

The default ports must be overridden or the command collides with the running server and
fails with `Address already in use`.
