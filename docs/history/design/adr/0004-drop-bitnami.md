# ADR-0004: Remove all Bitnami charts, images and the common library

## Status
Accepted.

## Context
Since 28 August 2025 Bitnami images moved to an unmaintained legacy repository and the
maintained catalogue sits behind a paid subscription. The existing repo already works around
this by pinning `bitnamilegacy/` image paths.

The dependency is deeper than images. `common: 2.31.1` — the Bitnami library chart — is a
declared dependency of all 23 authored charts, and those charts are written in its dialect:
`common.tplvalues.render`, `common.affinities.pods`, `common.compatibility.renderSecurityContext`,
`resourcesPreset`. The leading edge has already been felt: `common.warnings.rollingTag` had to
be stripped from vendored charts by hand.

## Decision
Remove all of it: the redis, postgresql, minio, nginx and keycloak charts, the copied values
files, the images, and the `common` library chart along with its idiom.

Replacements: CloudNativePG for Postgres; Valkey for cache; the Keycloak Operator for
Keycloak; nothing for nginx — the per-app static-asset servers are deleted rather than
replaced (five releases, ~5,000 lines, serving a theme CSS file that belongs in the frontend
image); object storage is deferred to ADR-0009.

## Consequences
Deletes 46,858 lines of copied values immediately. The real work is not the charts but the
`common` library idiom, which is why chart templates are read as reference rather than ported
(ADR-0001).

`resourcesPreset` goes with it. Resources are accepted verbatim, defaulting to empty, with
Kyverno flagging anything unset in prod and VPA in recommender-only mode replacing guesses
with measurements. The preset indirection hid the real numbers.
