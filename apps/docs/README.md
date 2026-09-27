# Docs

Upstream chart at git tag `v5.5.0`, path `src/helm/impress`. Everything below is a thing
that cost time to find.

## Chart values the design set gets wrong

| Design set says | Actually |
|---|---|
| `backend.envVarsFrom` | `backend.envFrom` |
| `backend.podDisruptionBudget.enabled` | `backend.pdb.enabled` |
| `backend.serviceMonitor.enabled` | no such key; the chart has **no** ServiceMonitor template |

And one the chart itself gets wrong: its `values.yaml` documents `envFrom` entries as
`- secret: {name: …}`. The chart passes the list straight through `toYaml` into the pod
spec, where the field is `secretRef`. Kubernetes 1.34 rejects the documented form with
`unknown field "envFrom[0].secret"` — confirmed by server dry-run before deploying.

`appVersion` is `latest`, so `image.tag`, `frontend.image.tag` and `yProvider.image.tag`
are all pinned explicitly.

## Celery OOMKills itself on the chart defaults

The default `celery` args carry no `--concurrency`, so it preforks one process per CPU —
ten on this node, each a whole Django. The container is killed with exit 137 a few seconds
after a startup log that looks completely healthy. Pinned to 2.

## `/media` is the surround's media proxy

`mediaProxy` in surround.yaml — `charts/platform-app/templates/mediaproxy.yaml` says why.
Verified: a restricted document's attachment is 403 anonymously and 200 with a session,
and public documents are readable by anyone, which is what `link_reach` says should happen.

## The theme file REPLACES upstream's default, it does not merge

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

## The theme JSON is cached in Redis for 24 hours

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

## The waffle

`waffle` is the gaufre. Without the key the switcher does not render at all (v5.5.0's
shipped default). With it, `LaGaufreV2` draws the button and loads two things by URL, both
of which default to the French government's: the widget script (`widgetPath`, from
`static.suite.anct.gouv.fr` — without it there is no switcher) and the service list
(`apiUrl`, `{services: [{name, url, logo, maturity}]}`, from `lasuite.numerique.gouv.fr`;
`data.services` is the same list inline). Both point at Docs' own origin here:
`/custom/gaufre.js` and `/custom/services.json`, served by the surround's `staticFiles`
(`apps/README.md`, The switcher). The list is the control plane's, from the enabled apps.

## Restoring the legacy data

Both halves are needed and neither is useful alone (`backups/*/MANIFEST.md`).

The database restores as the `docs` role, which cannot create the two `unaccent` helper
functions the dump carries — they are `LANGUAGE c` and owned by `postgres` upstream. Create
`public.immutable_unaccent(regdictionary, text)` and `public.f_unaccent(text)` as superuser
first, or the two trigram indexes on `impress_user` are silently missing afterwards. The
`pg_trgm` / `unaccent` extensions themselves are pre-created by the CNPG `Database`, so
those errors in the restore log are expected and harmless.
