# platform-app

The surround. It creates everything *around* what an upstream chart's release created
(`docs/history/design/04-platform-charts.md`). It creates almost nothing that runs — the one
exception is the media proxy, which is a route's backend rather than part of the
application; `docs/adr/0109` argues that case. Every key is described in
`values.schema.json`; this file is how the pieces fit.

## What actually does something on this cluster

| Object | Status here |
|---|---|
| `HTTPRoute` | **Real.** The only way traffic reaches an app. |
| `BackendTrafficPolicy` | **Real.** Body limits and timeouts; HTTPRoute cannot express either. |
| `PodDisruptionBudget` | Real when replicas > 1. Off at the `small` profile, where it could only block drains. |
| `NetworkPolicy` | **Emitted, NOT enforced** — `docs/adr/0103`. Never cite it as segmentation. |
| `HTTPRouteFilter` | **Real.** A 403 at the edge for `routes[].deny`. |
| media proxy | **Real, and it runs.** Off unless `mediaProxy.enabled` — `docs/adr/0109`. |
| static files | **Real.** Off unless `staticFiles.enabled`, which also adds the `static` route: an nginx serving `filesConfigMap` (the switcher scripts, default `<app>-gaufre`) and `servicesConfigMap` (the service list, default `office-services`) under `/custom/`. |

## Routes are grouped by backend, not by path

An `HTTPRoute` carries paths; a `BackendTrafficPolicy` attaches to an `HTTPRoute`. So paths
that need different traffic treatment cannot share an object, and the values shape is one
entry per route rather than one per path:

```yaml
routes:
  - name: api
    host: docs                            # -> docs.<baseDomain>
    backend: {name: docs-backend, port: 80}
    paths: [/api, /admin, /static]
    requestBuffer: 100Mi                  # reject bodies above this
    timeout: 300s                         # slow is not hung
  - name: collaboration-ws
    host: docs
    backend: {name: docs-yhub, port: 443}
    paths: [/collaboration/ws/]
    websocket: true                       # no buffer, no request timeout, long idle
```

`websocket: true` and `requestBuffer` together is a **render-time failure**, not a warning.
Buffering a request that never ends is how you break a websocket, and an editing session is
one request that legitimately lasts all day.

## Denying a path at the edge

Some upstream applications publish an admin surface on the same host and port as the
application — Collabora's console is on `/browser/dist/admin/`, its metrics on
`/cool/getMetrics`. `deny` puts a 403 in front of them:

```yaml
routes:
  - host: collabora
    backend: {name: collabora-online, port: 9980}
    paths: [/]
    websocket: true
    deny: [/browser/dist/admin, /cool/adminws, /cool/getMetrics]
```

It renders a second rule on the same `HTTPRoute` and an `HTTPRouteFilter` that returns 403.
Gateway API resolves overlapping matches by specificity, so the longest prefix wins and the
deny rule beats `/` no matter what order they appear in. The deny rule has **no**
`backendRef` on purpose: if the filter ever fails to resolve, the request 500s rather than
reaching the backend it was there to protect.

This is edge policy, not authentication. It stops the admin surface being reachable from
the internet; it is not a reason to leave its password weak.

## The media proxy

La Suite's applications authorise an attachment by subrequest — a proxy asks the backend
"may this session read this key?" and replays the S3 authorization headers it answers with.
Upstream ships that as ingress-nginx annotations, which Envoy Gateway cannot express
(`extAuth.http.path` is a prefix and Envoy appends the original path to it, so the check
404s and every request is denied). `docs/adr/0109` has the full argument.

```yaml
mediaProxy:
  enabled: true
  auth: {service: drive-backend, port: 80, path: /api/v1.0/items/media-auth/}
  objectstore: {bucket: drive}
  locations:
    - {path: "/media/preview/"}
    - {path: "/media/", headers: {Content-Disposition: attachment}}
```

Every location gets `Content-Security-Policy: default-src 'none'` whether or not it is
listed in `headers`. That is not decoration: these bytes are user uploads served from the
application's own origin, so without it a stored `.html` or `.svg` is a stored-XSS
primitive against every session on that host.

The Deployment's selector is `app.kubernetes.io/name: <app>-media-proxy`, not the release
selector, because a Deployment's selector is immutable and this one matches the object Docs
already runs from a hand-written manifest — so that release can be adopted rather than
recreated.
