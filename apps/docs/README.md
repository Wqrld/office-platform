# Docs

## What runs

`docs.${BASE_DOMAIN}`: DINUM's Docs (`impress`) — the Django backend, its Celery worker,
the frontend, the `yProvider` collaboration server, and three Jobs (`migrate`,
`createsuperuser`, and the search-flags Job below). The usual three releases
(`apps/README.md`); beside them, `oidc-refresh-key.yaml` is the Fernet key for the OIDC
refresh token search needs.

### `/media` is the surround's media proxy

`mediaProxy` in surround.yaml — `charts/platform-app/templates/mediaproxy.yaml` says why.
Verified: a restricted document's attachment is 403 anonymously and 200 with a session,
and public documents are readable by anyone, which is what `link_reach` says should happen.

### The waffle

`waffle` is the gaufre. Without the key the switcher does not render at all (upstream's
shipped default, as of v5.5.0). With it, `LaGaufreV2` draws the button and loads two things
by URL, both of which default to the French government's: the widget script (`widgetPath`,
from `static.suite.anct.gouv.fr` — without it there is no switcher) and the service list
(`apiUrl`, `{services: [{name, url, logo, maturity}]}`, from `lasuite.numerique.gouv.fr`;
`data.services` is the same list inline). Both point at Docs' own origin here:
`/custom/gaufre.js` and `/custom/services.json`, served by the surround's `staticFiles`
(`apps/README.md`, The switcher). The list is the control plane's, from the enabled apps.

## Pins and forks

Upstream chart `src/helm/impress` at git tag `v5.7.0` (`suitenumerique-docs` in
`charts/control-plane/templates/sources.yaml`); `image.tag`, `frontend.image.tag` and
`yProvider.image.tag` are `v5.7.0` too (`apps/README.md`, Conventions). No fork. On a
bump, read Gotchas, The theme file, first.

## Install order / first admin

`docs: {requires: [find]}` in `charts/control-plane/apps.yaml`: Find must exist before the
search-flags Job and reindex run, so `app-docs` waits for `app-find`. The admin account is
the `createsuperuser` Job's (`apps/README.md`, Conventions).

### Search needs a 20-minute token, with Find in its audience

Both are on Docs' client in `charts/control-plane/apps.yaml`.

- **`accessTokenLifespan: 1200`, and it must exceed 900.** At login mozilla-django-oidc
  sets `oidc_id_token_expiration = now + OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS`, whose default
  is 900 s and which Docs does not expose, so the refresh middleware does nothing for the
  first 15 minutes. At the realm's 300 s the token dies at minute 5 and search silently
  falls back to titles until minute 15. After the first refresh lasuite tracks the real
  `expires_in`, so only that first window is wrong.
- **`audiences: [find]`.** Without `find` in the token's `aud`, Keycloak refuses to
  introspect a Docs token for Find and answers `active: false`: Find 400s, and Docs
  swallows that into the title-only fallback. Verified: a fresh token introspects as
  inactive until the mapper exists.

### The search-flags Job

`backend.job` is the chart's generic job slot (unused upstream, `command: []`), so no
`extraObjects` is needed for it. Without `flag_find_full_text_search` the whole feature is
dark: `_get_search_type()` returns TITLE and Docs never calls Find. The `waffle_flag` CLI
is unreliable, so the Job uses the ORM; it is a hook because its name never changes
(`apps/README.md`, Conventions).

### Restoring the legacy data

Both halves are needed and neither is useful alone (`backups/*/MANIFEST.md`).

The database restores as the `docs` role, which cannot create the two `unaccent` helper
functions the dump carries — they are `LANGUAGE c` and owned by `postgres` upstream. Create
`public.immutable_unaccent(regdictionary, text)` and `public.f_unaccent(text)` as superuser
first, or the two trigram indexes on `impress_user` are silently missing afterwards. The
`pg_trgm` / `unaccent` extensions themselves are pre-created by the CNPG `Database`, so
those errors in the restore log are expected and harmless.

## Gotchas

Everything below is a thing that cost time to find.

### Chart values the design set gets wrong

| Design set says | Actually |
|---|---|
| `backend.envVarsFrom` | `backend.envFrom` |
| `backend.podDisruptionBudget.enabled` | `backend.pdb.enabled` |
| `backend.serviceMonitor.enabled` | no such key; the chart has **no** ServiceMonitor template |

And one the chart itself gets wrong: its `values.yaml` documents `envFrom` entries as
`- secret: {name: …}` (`apps/README.md`, Conventions) — confirmed by server dry-run before
deploying.

### Celery OOMKills itself on the chart defaults

The default `celery` args carry no `--concurrency`, so it preforks one process per CPU —
ten on this node, each a whole Django. The container is killed with exit 137 a few seconds
after a startup log that looks completely healthy. Pinned to 2.

### The theme file REPLACES upstream's default, it does not merge

`backend.themeCustomization` renders a ConfigMap mounted over the whole theme directory
at `/app/impress/configuration/theme`, so our `default.json` hides upstream's. Anything
in upstream's `backend/impress/configuration/theme/default.json` that we do not restate
is simply gone.

This is not cosmetic. Dropping `header.icon` removes the top-left logo *and* hides the
product title: `LeftPanelHeader.tsx` renders no `<Image>` when `icon` is absent, and gives
the `<h1>` the class `sr-only` when `icon.withTitle` is not true. The header therefore
degrades to an empty 68px box with an invisible heading, which reads as a broken CSS rule
rather than a missing config key. The same replacement silently dropped `favicon`,
`home.icon-banner`, `onboarding` and `help`; `onboarding.enabled` is the only truthy key
keeping the help menu rendered at all (`HelpMenu.tsx`).

All five are restored in `release.yaml` at upstream's values. When bumping the Docs
version, diff that file against the new tag's `default.json` before anything else.

### The theme JSON is cached in Redis for 24 hours

`backend.themeCustomization.file_content` renders into a ConfigMap that Django reads once
and caches for `THEME_CUSTOMIZATION_CACHE_TIMEOUT` (86400). **Editing it and reconciling
changes nothing users can see** until that expires. To force it:

```
kubectl -n office-data exec deploy/valkey-cache -- \
  valkey-cli --user docs --pass "$(kubectl -n office-data get secret valkey-cache-users \
    -o jsonpath='{.data.docs}' | base64 -d)" -n 1 --scan --pattern 'docs*theme*'
```

then `DEL` what it lists. Confirm with `curl https://docs.<domain>/api/v1.0/config/`,
whose `theme_customization` key is what the frontend actually renders.

## Upstream PRs

None recorded.
