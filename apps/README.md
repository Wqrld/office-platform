# apps/

One directory per application, each its own Flux Kustomization (`app-<name>`, emitted by
the control plane for every enabled app). Three releases per app, in order:

| File | Release | What it is |
|---|---|---|
| `deps.yaml` | `<app>-deps` (platform-deps) | everything the app needs before it starts: datastore Secrets, OIDC client, bucket, generated and shared tokens |
| `release.yaml` | `<app>` (the upstream chart) | the application, with the platform's Secrets wired in |
| `surround.yaml` | `<app>-platform` (platform-app) | what goes around it: routes, traffic policies, NetworkPolicy, PDB, media proxy, static files |

Secrets must exist before the workload that reads them, so they cannot come from the
surround; the surround attaches to workloads, so it cannot come first. LiveKit and
Collabora skip what they do not need.

Every `kustomization.yaml` lists its resources explicitly: dropping a file into a directory
must not silently deploy it. `../namespace.yaml` is shared — `${APP}` is substituted per
Kustomization — and the size profile (`overlays/size-<size>`) is applied as a component by
the control plane, so nothing here knows which size it runs at.

`networkPolicy` is on by default and NOT enforced on this cluster (adr/0103): Flannel ships
no policy controller. The egress graph is written down so it starts working the day a
policy-capable CNI arrives; do not cite it as segmentation.
