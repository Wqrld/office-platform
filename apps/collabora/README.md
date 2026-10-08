# Collabora Online

## What runs

`collabora.${BASE_DOMAIN}`: the WOPI editor Drive embeds — one coolwsd pod, by design (One
replica, below). It has no database, no cache, no bucket and no OIDC client: it holds no
state at all and never talks to Keycloak. Drive mints a short-lived WOPI access token and
Collabora authenticates back to Drive with that alone. `collabora-deps` therefore holds only
the generated admin credential, and `office-collabora` enforces PSA `baseline`, not
`restricted` (the four capabilities, below).

## Pins and forks

Chart `collabora-online` 1.3.5 from Collabora's own Helm repository, image
`collabora/code:26.04.3.2.1`, both pinned in `release.yaml`. Collabora is not a La Suite
application and it **does** publish a chart repository, so `adr/0104` (charts from pinned
git tags) does not apply — this is an ordinary pinned `HelmRelease`. No fork.

## Install order / first admin

No `requires` of its own; Drive requires it (`charts/control-plane/apps.yaml`), because
Drive's `configure-wopi` Job calls its discovery at install. There is no first admin: the
admin console is off (below).

## Gotchas

Everything below cost time to find.

### It will not start on this cluster without four capabilities

The stock image fails with `Setting ShutdownRequestFlag: Failed to spawn coolforkit`, a
few hundred lines into an otherwise healthy startup log, **whether or not** a
`securityContext` is set. Measured both ways on this cluster before the cause was clear.

coolwsd builds a chroot jail per document, and `/usr/bin/coolforkit-caps` carries file
capabilities:

```
$ getcap /usr/bin/coolforkit-caps
/usr/bin/coolforkit-caps cap_chown,cap_fowner,cap_sys_chroot=ep
```

A file capability can only grant what is already in the container's **bounding** set.
CRI-O's default bounding set has neither `SYS_CHROOT` nor `MKNOD`, so the file caps grant
nothing and the fork fails. That is why the default `securityContext: {}` fails too — the
problem is not something we dropped, it is something the runtime never granted.

```yaml
securityContext:
  runAsNonRoot: true
  capabilities:
    drop: ["ALL"]
    add: ["CHOWN", "FOWNER", "MKNOD", "SYS_CHROOT"]
  seccompProfile: {type: RuntimeDefault}
```

All four are inside PSA `baseline`; none is inside `restricted`. That is why
`office-collabora` enforces `baseline` — here that choice is load-bearing rather than
inherited.

`allowPrivilegeEscalation: false` is deliberately **absent**. `no_new_privs` makes the
kernel ignore file capabilities on `execve`, which breaks this exactly as dropping the
capabilities does. The container still runs as uid 1001 with an empty permitted set.

Verified working after the change: `Forked kit`, `Have 1 spare child`, and the kit reports
`adms_seccomp=ok adms_contained=ok`.

### The jail is copied, not bind-mounted, and that is expected here

The log carries these at startup and they are **not** errors to chase:

```
ERR  enterMountingNS, CLONE_NEWUSER unshare failed (ENOSYS: Function not implemented)
ERR  Failed to bind-mount [/opt/cool/systemplate] -> [.../cool_test_mount]
WRN  The systemplate directory is read-only ... Will have to clone dynamic elements
```

Creating the mount namespace needs unprivileged user namespaces, which this kernel does
not offer the container. coolwsd falls back to copying the template into each jail — the
kit reports `adms_bindmounted=slow`. Documents open correctly; the first open of a session
is slower and each jail costs disk. Revisit only if document-open latency becomes a real
complaint.

### One replica, and it is not a sizing decision

Every viewer of a document must reach the pod that holds it. nginx does that by hashing
`$arg_WOPISrc`; Envoy Gateway's consistent hash can key on a header, a cookie or the source
IP — **not on a query parameter**. With two replicas, two people editing one file get two
pods and two divergent copies.

The chart's own default is an HPA from 2 to 100 replicas. It is turned off, not tuned.
Raising the replica count requires solving affinity first — the chart's `reverseProxy`
sidecar (an in-namespace nginx that hashes `WOPISrc`) is the intended answer, and the WOPI
proof key stops being optional at the same moment.

### `server_name` is mandatory

Without it, `/hosting/discovery` advertises the editor at `https://localhost:9980/...`,
which is the URL the browser is then told to load. Verified:

```
$ curl .../hosting/discovery | grep -o 'urlsrc="[^"]*"' | head -1
urlsrc="https://collabora.example.org/browser/cc5614c67e/cool.html?"     # with server_name
urlsrc="https://localhost:9980/browser/4610258811/cool.html?"            # without
```

### The alias group list is an allow-list only in `groups` mode

`--o:storage.wopi.alias_groups.mode=groups` is what makes `aliasgroups` mean "refuse any
other WOPI host". Without that flag the list is advisory and Collabora will fetch and edit
a document from any host that asks — on a public address, that is an open
document-conversion service run at our expense.

### The admin console is off, in three places

It sits on the same host and port as the editor, at `/browser/dist/admin/admin.html`, with
`/cool/adminws` and `/cool/getMetrics` beside it. `getMetrics` enumerates every open
document.

1. `--o:admin_console.enable=false` — the console does not exist.
2. `surround.yaml` returns **403 at the Gateway** for all three prefixes.
3. The credentials are generated in-cluster rather than the chart's `admin`/`examplepass`.

The first one is load-bearing, not belt-and-braces. The Gateway stopped unescaping `%2F` so
that Collabora's own session URLs survive (`apps/drive/README.md`), and a `PathPrefix` deny
rule matches the raw path — so `/browser/dist%2Fadmin/admin.html` slipped past the edge and
reached coolwsd, which answered 401. Measured. Turning the console off removes the target
instead of chasing path spellings.

### No WOPI proof key

The chart can generate one, and its own values file says not to under Flux: the generator
reads the previous Secret back from the live cluster, which `helm template` does not do, so
every reconcile mints a fresh key and rotates it under the running pods.

We do not need one. Drive does not verify the `X-WOPI-Proof` header — its own WOPI tests
pass `proof_keys: {}` — and with one replica coolwsd's per-process ephemeral key is
self-consistent. This decision is tied to the replica count: revisit both together, never
one alone.

## Upstream PRs

None recorded.
