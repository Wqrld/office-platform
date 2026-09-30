# 0107 — `platform-deps` stops at the namespace boundary

**Status:** accepted · **Date:** 2026-09-03 · **Amends:** design set `history/design/06-datastores.md`,
`history/design/03-repo-layout.md`

## Context
The design set has `platform-deps` create "CNPG `Database` + `Role` + extensions" and the
equivalent for cache and object store — i.e. the app's release provisions its own datastores.

Two of those cannot work from a release that lives in the application's namespace:

- **CNPG `Database`** is namespace-bound to its `Cluster`. Ours is `office-pg` in
  `office-data`; a release in `office-docs` cannot create a `Database` for it without
  templating an explicit foreign namespace into a shared one.
- **Valkey ACL users** are a map (`auth.aclUsers`) inside the *valkey-cache* and
  *valkey-broker* HelmReleases' values. Adding a user is an edit to another release. No
  chart in the app's namespace can express it at all.

`GarageBucket` and `GarageKey`, by contrast, are already app-namespaced and work fine.

## Decision
`platform-deps` owns only what lives in the application's own namespace:

| Owned by `platform-deps` (app namespace) | Stays in `30-platform` (`office-data`) |
|---|---|
| `ExternalSecret` → app-shaped Postgres Secret | CNPG `Cluster`, `Database`, `Role` |
| `ExternalSecret` → app-shaped cache/broker Secret | Valkey instances and their `aclUsers` |
| `ExternalSecret` → the OIDC Secret | The ESO password generators |
| `ExternalSecret` → generated app secrets | The `ClusterSecretStore`s |
| `GarageBucket` + `GarageKey` | The Garage `Cluster` |

So `platform-deps` is a **credential-shaping** chart with one provisioning exception
(object storage), not a provisioning chart.

## Reasoning
The alternative is templating objects into `office-data` from an app's release. That is
possible for CNPG and impossible for Valkey, so it half-solves the problem while making an
application's Helm release the owner of objects in a shared namespace — where an uninstall
reaches across a boundary it should not cross. A clean line that is honest about the seam
beats a partial abstraction that hides half of it.

The cost is stated rather than hidden: **adding an application still touches the platform
layer** — one line in `charts/platform-tenants/values.yaml` and one in each of
`platform/valkey/{cache,broker}.yaml` for the ACL user (amended 2026-09-30: this was three
hand-written files until the `platform-tenants` chart replaced them).

## Consequences
- `platform-deps` shrinks, which is the right direction for a chart whose value is removing
  boilerplate rather than adding indirection.
- The datastore contract's `mode: managed` / `mode: external` split survives, but `managed`
  means "the platform layer already provisioned it" rather than "this release provisions it".
- If Valkey ever grows an ACL source outside its own values — a Secret or a file — revisit
  the cache half. CNPG would still need the foreign-namespace decision made separately.
- *Amended 2026-09-30:* the platform-layer cost above is now zero lines. Each app's
  provisioning fields live in its entry in `charts/control-plane/apps.yaml`, which the
  control plane hands to `platform-tenants` as TENANTS_JSON — every app, enabled or not, so
  this ADR's "provisioned regardless" holds by construction. The ACL users still live in the
  Valkey releases' values, but those values are now a ConfigMap the tenants chart renders and
  each instance reads through `valuesFrom`: the seam stays where this ADR drew it (the
  platform layer owns `aclUsers`), it is just no longer hand-written.
