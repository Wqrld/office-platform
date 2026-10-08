# 0116 — The Keycloak session outlives the applications' sessions

**Status:** accepted · **Date:** 2026-10-08

## Context
The `office` realm never set its session lifetimes, so it ran on Keycloak's defaults:
an SSO session ends after 30 minutes without a token request (`ssoSessionIdleTimeout`)
and after 10 hours whatever happens (`ssoSessionMaxLifespan`). A refresh token is valid
only as long as its session.

The applications keep their own Django sessions, longer than that: Docs and Meet set
`SESSION_COOKIE_AGE` to 12 hours. Most of them never go back to Keycloak once the user
has logged in. Docs' full-text search does. It forwards the user's access token to Find
and first refreshes it (`storeRefreshToken`, `apps/docs/deps.yaml`), and it refreshes
only when the user searches. After 30 minutes without a search, the refresh token has
expired with the session. Keycloak answers `invalid_token`, "Token is not active", and
Docs returns 401 for every search while the rest of Docs keeps working. Find is never
called, and nothing in Docs logs why. Only logging in again brings search back.

## Decision
`ssoSessionIdleTimeout` and `ssoSessionMaxLifespan` are 12 hours
(`charts/platform-tenants/files/realm.yaml`), equal to the longest application session
that relies on a refresh token. Their RememberMe variants stay unset and fall back to
these. keycloak-config-cli applies them to the existing realm, so existing clusters pick
them up on upgrade.

A Keycloak session lifetime must stay at least as long as the `SESSION_COOKIE_AGE` of
any application that refreshes its token.

## Consequences
- Search keeps working for as long as the user's Docs session lasts.
- A Keycloak session left idle now stays valid for up to 12 hours instead of 30
  minutes. On a shared device, a user who walks away without logging out stays logged
  in to the platform for that long. That is how the applications behaved already; the
  SSO session now behaves the same.
- Logging out of Keycloak still ends the session at once, and so does disabling a user.
- Raising an application's `SESSION_COOKIE_AGE` above 12 hours means raising these too.
