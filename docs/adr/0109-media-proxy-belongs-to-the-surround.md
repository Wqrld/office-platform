# 0109 — the media proxy belongs to the surround

**Status:** accepted · **Date:** 2026-09-03 · **Amends:** design set `history/design/04-platform-charts.md`

## Context
`platform-app` was defined as the chart that "creates nothing that runs". Docs broke that on
day one: `/media` cannot be a plain route to either the backend or the object store, so it
shipped as 131 hand-written lines of nginx in `apps/docs/media-proxy.yaml`, logged as
an escape hatch used once.

Drive needs the same thing. Its media-auth endpoint is `/api/v1.0/items/media-auth/` rather
than `…/documents/…`, it has a second location (`/media/preview/`), and `/media/` gets a
`Content-Disposition: attachment` header the preview must not have. Everything else — the
`auth_request` dance, the header replay, the path-style proxy_pass, the `substitute:
disabled` annotation that stops Flux blanking every `$variable` — is identical.

Copying it would be the second hand-written copy of a 131-line file, and the design set's
own P5 rule says a pattern used twice is close to being a feature.

## Why it cannot be an ext-auth policy
Envoy Gateway's `SecurityPolicy` extAuth is the obvious answer and it does not work.
`extAuth.http.path` is a **prefix**: Envoy appends the original request path to it, so the
authorisation check arrives at Django as
`/api/v1.0/items/media-auth/media/<uuid>/attachments/x.png`. That matches no route, 404s,
and denies every request. The view also needs the original URL in a header of its own,
which extAuth does not send. Verified against the CRD text and both applications' views.

## Decision
The media proxy becomes a `platform-app` feature (`mediaProxy.enabled`), and `platform-app`
stops claiming it creates nothing that runs.

The justification is that this pod **is the `/media` route's implementation**, not part of
the application. It exists only because our Gateway cannot express what upstream's ingress
annotations express. It is routing, and routing is what the surround owns.

## Consequences
- Drive gets `/media` in 8 lines of values instead of 131 lines of manifest.
- Docs' hand-written `media-proxy.yaml` is now a duplicate. It is **deliberately left in
  place for now**: moving it means a live Deployment, Service and ConfigMap changing owner
  from kustomize-controller to helm-controller, which needs the same two-phase handover the
  rest of Docs went through (annotate with `meta.helm.sh/release-*` and
  `kustomize.toolkit.fluxcd.io/prune: disabled`, then swap the manifest for the release).
  The chart's selector is `app.kubernetes.io/name: <app>-media-proxy`, byte-identical to
  what Docs runs, precisely so that handover adopts rather than recreates.
- `Content-Security-Policy: default-src 'none'` is applied by the template, not by the
  caller. It is the only thing standing between a stored `.svg` and a session on the same
  origin, and an app author must not be able to forget it.
- If a third application needs a *different* auth-subrequest shape, this becomes a chart of
  its own rather than growing more knobs.
