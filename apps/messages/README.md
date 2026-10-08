# Messages

## What runs

`messages.${BASE_DOMAIN}` — shared and personal mailboxes, collaborative inbox. La Suite's
Messages (`suitenumerique/messages`): Django and Celery like Docs, plus the two things no
other app here has — an inbound MTA on port 25, and outbound delivery straight to every
recipient's MX.

**Off by default** (`apps.messages: false`): an organisation turns it on once port 25 is
open in both directions and the records under Mail DNS exist.

The usual three releases (`apps/README.md`): `messages-deps`, `messages`,
`messages-platform`.

| Workload | Image (the fork's, see Pins) | Port | Notes |
|---|---|---|---|
| backend | `messages-backend` | 8000 | API, admin, and the MDA the MTA delivers into |
| celery-worker | `messages-backend` | — | inbound and outbound delivery, imports, indexing, **and beat** |
| frontend | `messages-frontend` | 8080 | Caddy: the SPA, proxies `/admin` and health checks |
| mta-in | `messages-mta-in-py` | 2525 (Service 25) | SMTP in; asks the backend per recipient |
| mpa | `messages-mpa` | 8010 | rspamd behind nginx; the backend's spam check |

Plus the chart's `migrate` and `createsuperuser` Jobs, as in Docs.

**The worker is one replica at every size.** `worker.py` runs the beat scheduler in the
same process unless told `--disable-scheduler`, and two schedulers run every periodic task
twice. Sizes scale it by `--concurrency`. A separate beat would need a chart component
upstream does not have.

### Its own spellings

Django, so most of the `lasuite` family; two profiles are new (`env: messages`,
`charts/platform-deps/templates/_profiles.tpl`):

| Kind | Profile | Reads |
|---|---|---|
| postgres | `django` | `DB_*` |
| cache | `celery` | `REDIS_URL`, and `CELERY_BROKER_URL` without Docs' `DJANGO_` prefix |
| objectstore | `django-s3` | `AWS_S3_*`; `STORAGE_MESSAGE_{IMPORTS,BLOBS}_*` point at the same keys (release.yaml) |
| opensearch | `url` | `OPENSEARCH_URL` with the credential in it, `OPENSEARCH_CA_CERTS` |
| smtp | `django-prefixed` | `DJANGO_EMAIL_*` — Django's own notifications, not user mail |
| oidc | `django` | `OIDC_OP_*`, `OIDC_RP_*` |

**OpenSearch verifies the server**, unlike Find, so the platform's private CA is copied into
`messages-opensearch-ca` (`opensearch.caSecret`) and mounted where `OPENSEARCH_CA_CERTS`
says. The index name is fixed in the code (`messages`), so the role
(`search: [messages]` in `charts/control-plane/apps.yaml`) pins the name rather than a prefix.

### How mail flows

**In.** A sender connects to `mx.${BASE_DOMAIN}:25`, which is the Gateway (`smtp` listener,
`platform/gateway/gateway.yaml`). A TCPRoute hands the connection to `messages-mta-in`, and
a BackendTrafficPolicy prepends a PROXY v2 header — Envoy terminates TCP, so without it the
MTA would see Envoy as every sender and stamp and rate-limit every message as one IP. The
MTA asks the backend whether each recipient exists (a JWT signed with `MDA_API_SECRET`),
accepts, and delivers into the backend; the backend runs the inbound pipeline — rspamd,
DKIM/DMARC — as a Celery task.

**Out.** The worker connects to each recipient's MX on 25 directly (`MTA_OUT_MODE=direct`),
signs with the mail domain's DKIM key, and says `EHLO mx.${BASE_DOMAIN}`
(`MTA_OUT_EHLO_HOSTNAME`). The source address is the NODE's, not the Gateway's.

### Spam filtering: the MPA

rspamd, which the backend calls on every external message (`SPAM_CONFIG`). Fail-closed: if
it is unreachable, inbound mail is held and retried, not delivered unscanned — hence its
own disruption budget at `large`. Upstream's `src/mpa` could not run here as it was, so the
fork changes it (Upstream changes, 2-4). Greylisting is off: rspamd scans after the MTA has
accepted, so a greylist verdict filters nothing and only delays every first-time sender.

Its state (Bayes, reputation, ratelimits) lives in the cache Valkey through the backend's
own `REDIS_URL`; eviction there costs retraining, not mail. It runs as Lua scripts
(`@scripting`, which the shared ACL line allows), tested against exactly those permissions.

## Pins and forks

### Where the chart comes from

Written in the application's repo at `src/helm/messages`, **copied from Docs'
`src/helm/impress`**: the backend, worker, frontend and Jobs as Docs has them, and two new
components in the same shape, `mtaIn` and `mpa`, both off by default. It comes from the
fork's git tag (`GitRepository` `wqrld-messages`, `charts/control-plane/templates/sources.yaml`),
the same tag that publishes the five images, so chart and images move together.

### Pins

The fork (`Wqrld/messages`), tagged `vX.Y.Z-office.N` so its tags never collide with
upstream's — `v0.9.0-office.1` today; the images carry the tag without the `v`. updatecli
tracks the fork's tags (`updatecli/updatecli.d/messages.yaml`) and moves the chart pin and
all five image tags. The fork's patches are the PR's, listed under Upstream PRs.

Two workarounds in `release.yaml` go with the fork's next fixes: `runAsUser: 1001` on the
backend (upstream's CI builds without `DOCKER_USER`, so the image is root) until the
fork's CI passes `DOCKER_USER`, and the backend's `/__heartbeat__` probe until the fork's
chart says it instead of Docs' `/__lbheartbeat__`.

## Install order / first admin

### Mail DNS

`./dns.py <cluster>` prints the platform's half. Before enabling the app:

1. `mx.${BASE_DOMAIN}` — A to the Gateway address (the wildcard covers it).
2. `_spf.${BASE_DOMAIN}` — `TXT "v=spf1 ip4:<egress> -all"`, where `<egress>` is every node
   address the worker can send from. Pin the worker to one node, or list them all.
3. **PTR** of each egress address → `mx.${BASE_DOMAIN}`, at the provider. Receivers compare
   it with the EHLO name; a mismatch is a spam score at best.
4. **Outbound 25 open at the provider.** It is blocked by default on this platform's provider
   (`charts/platform-deps/values.yaml`, smtp) — ask them to lift it before enabling.

Then per mail domain, once it exists in Messages (below): its MX (`10 mx.${BASE_DOMAIN}.`),
SPF include, DKIM and DMARC, exactly as the admin's DNS page for the domain lists them, or
`manage.py dns_check --domain <domain>`. One MX, not upstream's `mx1`/`mx2`: there is one
Gateway address to point them at (`MESSAGES_DNS_RECORDS` in release.yaml).

### Install order

Everything for a login client (Projects' README), plus mail:

1. **Mail DNS** above, and outbound 25 lifted at the provider.
2. Reconcile the platform layer: the tenants chart's Jobs add the `messages` OpenSearch user
   and the realm client (`kubectl -n office-data get job`, `-n office-identity`).
3. Reconcile apps; watch the migrate Job, then the MTA log for the first connection.
4. **A mail domain.** In `/admin/` as `admin@${BASE_DOMAIN}` (password in
   `messages-django`, `DJANGO_SUPERUSER_PASSWORD`), add the domain with `oidc_autojoin`.
   A realm user whose email is on that domain gets that address as its mailbox at their
   next login; everyone else logs in to an empty account. Publish
   the domain's records from its DNS page, then `./dns.py <cluster> --check` and a test
   message each way.

## Gotchas

### Known gaps

- **STARTTLS is self-signed.** Sending MTAs encrypt opportunistically and verify nothing, so
  this is encryption without authentication — which is what every MX gets from a sender
  unless the domain publishes MTA-STS or DANE. Publishing MTA-STS would need an ACME
  certificate for `mx.`, issued in `office-system` (the Gateway's HTTP listener admits only
  its own namespace's routes) and copied here.
- **Exports hand out an unreachable link.** A mailbox export is a presigned URL, signed
  against the in-cluster S3 endpoint; the user cannot open it. Drive's `publicEndpoint`
  pattern (adr/0110) would fix it, at the cost of publishing the bucket.
- **RBL lookups depend on the resolver.** rspamd resolves through the cluster DNS; Spamhaus
  and others refuse queries arriving from large public resolvers. If CoreDNS forwards to
  one, those checks answer nothing — give rspamd its own resolver if hit rates are low.
- **Egress address.** SPF and PTR name the nodes' address; a cluster that grows a node
  sends from an address SPF does not list until it is added.
- **Imports' bucket lifecycle.** Upstream expects a lifecycle rule to reap abandoned
  uploads (upstream's `messages/docs/imports.md`); nothing sets one on Garage.
- **The email claim is trusted.** Autojoin hands out the mailbox named by the Keycloak
  email, and the realm lets users edit their own email unverified — any realm user can
  claim any unowned address on an autojoin domain. Acceptable for a demo; before real use,
  make `email` admin-editable in the realm's user profile.
- **Sizing is unmeasured.** Starting points from Docs' measured Django; rspamd's memory is
  its maps and Hyperscan database, loaded at start.
- **The shared Valkey ACLs isolate nothing** — the same `~* &*` line every app has.

## Upstream PRs

One upstreaming PR carries the five changes below; the fork runs them now.

**When the PR lands:** the `GitRepository`'s url becomes `github.com/suitenumerique/messages`
at the tag that carries the chart, and the images go back to `ghcr.io/suitenumerique/…`
once upstream publishes the MPA and has patch 5.

### Upstream changes (the PR)

1. **The chart**, `src/helm/messages`. Divergences from Docs': the `envFrom` example says
   `secretRef:` (as Projects'); the MTA listens on 2525 in the pod — the chart drops every
   capability and runs non-root, so it cannot bind 25 unless the runtime lowers
   `ip_unprivileged_port_start`, which Docker does and Kubernetes does not promise.
2. **The MPA on rspamd's stock configuration.** `src/mpa/rspamd/rspamd.conf` REPLACED the
   whole configuration, so rspamd ran with none of its modules configured. Now the stock
   configuration stays and `local.d/` overrides workers, logging and Redis.
3. **Redis from the environment**, with a password: `RSPAMD_redis_*`, or `RSPAMD_redis_url`
   split by `start.sh` — the backend's spelling, so one Secret feeds both. Was a hard-coded
   `redis:6379` with no authentication.
4. **Non-root MPA**, numeric `USER 1000:1000`, and **published** by `messages-ghcr.yml`.
5. **`MTA_OUT_EHLO_HOSTNAME`** — without it direct delivery says `EHLO <pod name>`, which
   matches no PTR. With a test (`core/tests/mda/test_smtp.py`).
