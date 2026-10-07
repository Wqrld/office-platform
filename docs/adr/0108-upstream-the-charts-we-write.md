# 0108 — Charts we write for La Suite apps should go upstream

**Status:** accepted, amended 2026-09-30 (Outcome) · **Date:** 2026-09-03 · **Relates to:** `0104`, design set `history/design/05-app-contract.md`

## Outcome
Decision points 3 and 4 held; 1 and 2 did not. Projects' and Messages' charts were written
straight into the application's own repo at `src/helm/<name>`, copied from Docs'
`src/helm/impress` so upstream reads them as theirs — never under `charts/` here, so the
licence question never arose (the app repos are MIT, and so is the chart). Each is consumed
from the fork's git tag, the same tag that publishes the images, until the upstream PR
lands; then only the `GitRepository` url changes. `platform-lib` and `tests/equivalence.py`,
named below, no longer exist. The Context and Decision are as written on 2026-09-03.

## Context
`0104` established that La Suite publishes no Helm repository and charts come from pinned
git tags in each application's own repo, at `src/helm/<name>`. That works for Docs, Drive,
Meet and People, which all ship one.

**Messages and Calendars did not, at the time** (`messages` v0.9.0, `calendars` v0.1.0).
Calendars' chart has since appeared on upstream's `main` and is served from our Helm repo
until the tag lands (`apps/calendars/README.md`); no chart of ours was written. The
decision below stands for the next app that has none.

Three facts make "just keep it in our repo" the wrong default:

1. **Upstream intends to ship charts.** `messages/docs/self-hosting.md` lists Kubernetes
   deployment as "Wait for Helm charts (coming in future releases)" and "might be supported
   in future releases with official Helm charts". So the chart we write is either the one
   they ship, or the one we throw away when they ship theirs.
2. **Nobody is doing it.** A GitHub search for `helm OR kubernetes in:title` across issues
   and pull requests returns **zero** results in both repos. The slot is open.
3. **Both repos are MIT. This repo is EUPL-1.2.** MIT flows into EUPL; EUPL does not flow
   into MIT. A chart written here under EUPL cannot later be contributed to an MIT repo
   without every contributor agreeing to relicense.

## Decision
Write the Messages and Calendars charts with upstreaming as the intended destination.

1. **Licence the chart sources MIT from the first commit**, not EUPL, and say so in a header
   in each chart directory. This is the decision that cannot be deferred — everything else
   here can be changed later, and this one cannot.
2. **Build them in this repo first**, under `charts/`, so they get `platform-lib`, the
   `tests/equivalence.py` harness and a fast edit loop.
3. **Prefer a pull request to a fork.** Open it against `src/helm/<name>` to match the
   layout Docs, Drive, Meet and People already use, so it reads as the missing piece of an
   established convention rather than a new one.
4. **Fork only as the PR's staging area, or if the PR stalls.** A pinned fork is a real
   fallback — `0104` already consumes charts from git tags, so a fork costs nothing new
   architecturally — but it carries a rebase burden forever, and a chart nobody upstream
   reviews is a chart that drifts from the app it deploys.

## Reasoning
The cost of upstreaming is a PR and some review latency. The cost of not upstreaming is
paid twice: once maintaining a chart against an application whose values and workloads move
without us, and again when upstream ships their own and we migrate to it anyway.

There is also a straightforward argument from what this platform is. These are public-sector
open source projects; we are deploying them for real and finding real gaps — Messages'
`mta-out` needing a smarthost because port 25 is blocked, Celery's default concurrency
OOMKilling itself, DINUM's own chart documenting `envFrom` entries in a shape Kubernetes
rejects. That knowledge is worth more in the upstream chart than in our private one.

Building here first is not a contradiction. It is where the chart can be wrong cheaply.

## Consequences
- **A licence header goes in before the first template.** Retrofitting it means chasing
  agreement from everyone who touched the file.
- **If the PR lands, the app moves from Tier 4 to Tier 1** — it stops being our chart and
  becomes an upstream chart plus a `platform-app` surround. That is a migration we should
  expect, not be surprised by; `platform-app` already exists for it.
- **Consumption changes with the destination.** A chart in this repo is built from the
  platform's own git tag (`0114`); a chart upstream or in a fork is a Flux `GitRepository` pinned to a
  tag, per `0104`. The app's HelmRelease changes `chartRef` to `chart.spec` when it moves.
- **`platform.workload` stays useful either way.** Bureaublad has no upstream to send a
  chart to, so the helper has a consumer regardless of how Messages and Calendars land.
- If upstream ships a chart with a materially different shape before ours is reviewed, take
  theirs. The point is not that our chart wins; it is that the app is deployable on
  Kubernetes by anyone.
