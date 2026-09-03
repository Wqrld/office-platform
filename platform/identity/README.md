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
