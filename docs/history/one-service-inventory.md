# One service inventory — design

**Built 2026-09-21**, as below, with three deviations: the list is in name order, not table
order (the table is a YAML map; Helm iterates it sorted); the ConfigMap value carries a
trailing newline — Flux substitutes on the YAML text and a one-line value starting with `{`
comes back as a map, a block scalar stays a string — and `metadata` is block style, since a
flow map cannot hold a plain `${APP}`; and `switcher.js` did not just swap its literal for a
fetch, it dropped its panel entirely and hands its button to `gaufre.js` (part C below).
Meet serves `/custom/` from its own nginx, so it gets the list through a projected volume
rather than `staticFiles`. Not yet seen in a browser. What follows is the design as written.

The suite's list of services is stated to users three times, once per switcher:
`apps/switcher.js` (`SERVICES`, for Drive and Meet), `apps/calendars/services.json`
(Calendars' gaufre) and `apps/docs/release.yaml` (`waffle.data.services`). Each carries a
comment telling the editor about the other two. None of them knows which apps are on: a
cluster with `apps.meet: false` shows Meet in every switcher, linking to a host with no
route and no SAN. The list is a fact the control plane already holds — `apps.yaml` plus the
enabled set — so this derives it there and lets each frontend fetch it.

**Shape.** One entry per app in the table the control plane already reads, one generated
JSON file served by every app from its own origin, three consumers that fetch it.

```yaml
# charts/control-plane/apps.yaml — the existing table, one key more
docs: {requires: [find], hosts: [docs], switcher: {name: Docs, logo: /assets/icon-docs.svg, maturity: stable}}
drive: {requires: [collabora], hosts: [drive], switcher: {name: Drive, logo: /assets/logo-icon_beta.svg, maturity: stable}}
# collabora, find, livekit: no `switcher` — nothing a user opens
```

A helper renders the enabled apps' entries, in table order, with `https://<host>.<domain>`
and the logo path made absolute, then the fixed Account entry
(`https://id.<domain>/realms/office/account`), as one line of JSON in the widget's schema —
`{services: [{name, url, logo, maturity}]}`, which is what Calendars' gaufre already
reads — into `cluster-vars`:

```yaml
SERVICES_JSON: {{ include "platform.servicesJson" . | quote }}
```

One shared manifest beside `apps/namespace.yaml`, listed in every app's `kustomization.yaml`
the same way:

```yaml
# apps/services.yaml — `${APP}` and `${SERVICES_JSON}` are substituted per Kustomization
apiVersion: v1
kind: ConfigMap
metadata: {name: office-services, namespace: office-${APP}}
data: {services.json: '${SERVICES_JSON}'}
```

Its own ConfigMap, not a key in the switcher's: `drive-switcher` and `meet-frontend` carry
`substitute: disabled` for `switcher.js`, and this file needs substitution. `platform-app`'s
`staticFiles` grows a second source (`servicesConfigMap`, mounted beside `filesConfigMap`),
so every app that has a static server serves `/custom/services.json` from its own origin —
a same-origin fetch, no CORS.

**The three consumers.**

- **Calendars** — already fetches `FRONTEND_LAGAUFRE_WIDGET_API_URL`; point it at the
  generated file. `apps/calendars/services.json` is deleted; `gaufre.js` stays.
- **Drive, Meet** — `switcher.js` replaces its `SERVICES` literal with
  `fetch("/custom/services.json")` and builds the menu from the response, falling back to
  no menu rather than a broken one if the fetch fails. Same file, same ConfigMaps.
- **Docs** — `waffle.apiUrl: https://docs.${BASE_DOMAIN}/custom/services.json` replaces the
  `waffle.data` block, and `waffle.widgetPath: https://docs.${BASE_DOMAIN}/custom/gaufre.js`
  is added (below). Docs has no static server today: `staticFiles.enabled: true` in its
  surround and a `/custom` route, as Drive has, serving `gaufre.js` and `services.json`.

Verified against Docs v5.5.0 and the `@gouvfr-lasuite/ui-kit@0.28.0` it bundles:
`Waffle.tsx` spreads the theme's `waffle` object into `LaGaufreV2`, whose props are
`{apiUrl}` or `{data: ServicesResponse}` with `ServicesResponse = {services: [{name, url,
maturity?, logo?}]}`; `apiUrl` is handed to the widget's `init` as `api`, and both the
upstream widget and our `gaufre.js` fetch it and read `payload.services`. The backend
`json.load`s the theme file verbatim. So the one file serves all three.

**A finding on the way.** `LaGaufreV2` always injects `<script src={widgetPath ||
"https://static.suite.anct.gouv.fr/widgets/lagaufre.js"}>` — in `data` mode too. Docs'
theme sets no `widgetPath`, so today the list is ours but the switcher's code is loaded
from the French government's CDN on every Docs page, and a page that cannot reach it has
no switcher. `apps/docs/release.yaml` ("no call out ... at any point") and
`apps/docs/README.md` ("no external call") are wrong about this. `widgetPath` passes
through the spread, and `gaufre.js` was written as a drop-in for that widget's queue
protocol, so Docs serving it from `/custom/` closes the gap — independent of the rest of
this design, and worth doing first.

**What that buys.** An app switched off leaves the switchers with it, which is the bug.
Adding an app is one line in the table it already needs a line in. The Account entry and
its inline SVG live once. `tests/build.py`, which already asserts `apps.yaml` and `apps/`
agree, can assert `switcher.name` is set for every app with a host a browser opens.

**What it costs.**

- The `${SERVICES_JSON}` value is JSON inside a single-quoted YAML scalar inside a
  substitution. The Account logo is a data URI with `%`, `'` and `=`. Base64-encoding the
  value and decoding in a `configMapGenerator` is not available; instead the helper emits
  the logo as a path Docs already serves (`/assets/…`) or drops the inline SVG for a first
  letter, which `switcher.js` already renders when `icon` is null. Either removes the only
  awkward characters.
- One more fetch per page load, cached `maxAge: 300` by the static server, which is what
  Calendars pays today.
- **Verification needs a browser** — this was deferred in `REVIEW.md` §3 for that reason,
  and it is still true: three frontends, three mounts, and `e2e.py` is protocol-level.
  The check is: open each of the four apps, the switcher lists exactly the enabled apps and
  Account, every link opens. On demo with one app switched off, that app is absent.

**Lines.** Roughly −60 net: `services.json` (−40) and Docs' `waffle.data` block (−30) go;
`switcher.js` swaps a 7-line literal for ~8 lines of fetch; the table gains one key per
user-facing app (+4), the helper ~12, the ConfigMap manifest ~5, Docs' static server and
route ~10, the `staticFiles` second mount ~8. Small, and the count is not the reason — the
reason is the cluster with an app off.

**Order of work.**

1. Docs' static server, `gaufre.js` and `waffle.widgetPath` — the external script goes,
   nothing else changes; fix the two comments that claim it was already gone.
2. Helper, `SERVICES_JSON`, `apps/services.yaml`, `staticFiles.servicesConfigMap` — one
   commit, no consumer changed; goldens show the new ConfigMap and nothing else.
3. Calendars first (it already fetches), then `switcher.js`, then Docs. Each on demo, in a
   browser, before the next.
4. Delete `apps/calendars/services.json` and the three "keep in step" comments.

**Part C, one switcher implementation.** `switcher.js` (155 lines) was a second panel
beside `gaufre.js` (240) — its own CSS, menu and icon fallback. It is now the button only:
find the mount slot in Drive or Meet, draw the grid button, then load `/custom/gaufre.js`
from the same origin and push `["lagaufre", "init", {api: "/custom/services.json",
buttonElement, position, label}]` — exactly what `LaGaufreV2` pushes in Docs and
Calendars, so all four apps render one panel from one list.
