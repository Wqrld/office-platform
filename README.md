<div align="center">

# office-platform

**Your own office suite (documents, files, calendars, video calls, mail and project boards)
on your own domain, on one VPS or your own Kubernetes cluster.**

Built on [La Suite numérique](https://github.com/suitenumerique), the open-source
collaboration suite built by France's DINUM with European partners, and packaged as a single,
versioned, tested release you install with one command.

<img src="applications.png" alt="The app switcher: Calendars, Docs, Drive, Meet, Messages, Projects" width="274">

</div>

> [!NOTE]
> Much of the code in this repository was written with an LLM. Every change still has to
> pass the checks CI runs ([`AGENTS.md`](AGENTS.md)), but read what you deploy and review it before you rely on it
> in production.

## What you get

| | App | What it does |
|---|---|---|
| 📝 | **Docs** | Collaborative documents and notes, edited live together, with full-text search across them (Find) |
| 📁 | **Drive** | Files and folders, shared with people or links, with Office documents opened in Collabora Online |
| 📅 | **Calendars** | Shared calendars and meeting scheduling, plus a CalDAV endpoint for Thunderbird, iOS and Evolution |
| 🎥 | **Meet** | Video calls on LiveKit, with transcripts written into Docs |
| ✉️ | **Messages** | Shared and personal mailboxes with a collaborative inbox (optional, needs port 25) |
| 🗂️ | **Projects** | Boards, lists and cards for project management, with live collaboration |

One login (Keycloak, OIDC) for all of them and one app switcher across them. Each app is a
single switch in your config, so you can run the whole suite or only Docs and Drive.

## What it needs

You pick one of three sizes with `size` in your `cluster.yaml`. These are the numbers for
every app enabled:

| Size | For | CPU | RAM | Disk | A machine that fits |
|---|---|---|---|---|---|
| `small` | 5–50 people | 3.5 cores | 21 GiB | 42 GiB | one VPS: 6 cores, 32 GB, 80 GB SSD |
| `medium` | 50–500 people | 5.4 cores | 26.5 GiB | 67 GiB | one VPS: 8 cores, 48 GB, 120 GB SSD |
| `large` | 500–5,000 people | 31.5 cores | 81 GiB | 845 GiB | several nodes (not yet validated) |

CPU and RAM are what the pods reserve (`./measure.py render --size <size>`); the last
column adds room for Kubernetes itself. Disk is the volumes the platform claims. File
storage grows with use, and volumes can be grown but never shrunk.

## Quick start

On a fresh VPS (one machine with a public address; see [What it needs](#what-it-needs)):

```sh
git clone https://github.com/Wqrld/office-platform && cd office-platform
DOMAIN=office.example.org ACME_EMAIL=ops@example.org ./install.sh --k3s
```

Already have a cluster? Use `GATEWAY_IP=10.0.0.5 ./install.sh --existing` and
`./preflight.py cluster.yaml` to check it first. The full walk-through, from nothing to a
serving platform, is [`docs/install.md`](docs/install.md). Create the DNS records before the first
release (see [DNS](#dns)): one wrong record fails the certificate for every app.

---

## How it is built

Flux keeps your cluster in sync with this repository. You keep one file of your own,
`cluster.yaml` (start from [`examples/cluster.yaml`](examples/cluster.yaml)), that picks
your domain, size and apps, and points at a release of this repository. A release is a
git tag (`docs/releasing.md`).

```
charts/     the Helm charts that render the platform from your cluster.yaml
cluster/    Gateway and load balancer, if your cluster lacks them
infra/      operators: Postgres, secrets, object storage, certificates
platform/   shared services: gateway, Postgres, Valkey, search, Keycloak, object store
apps/       one directory per application
policy/     and tests/: the checks every change must pass
```

How it fits together, and the checks, are in [`AGENTS.md`](AGENTS.md); design decisions are in
[`docs/adr/`](docs/adr/).

## DNS

`./dns.py [cluster|cluster.yaml] [--check] [--zone]` prints the records a cluster needs, read
out of the config that will use them: the Gateway certificate's SAN list and every HTTPRoute
hostname, including the ones `platform-app` renders from `routes[].host`. `--check` resolves
each one and reports what disagrees.

Create them all *before* the first release: Let's Encrypt fails the whole certificate if a
single SAN fails validation, so one mispointed record is an outage for every application.

## Runbooks

`docs/install.md` — nothing to a serving platform: `./install.sh --k3s` on a fresh VPS,
`--existing` on a cluster you have.
`docs/releasing.md` — `./release.sh <version>`: one immutable tag for config and charts.

## Licence

[EUPL-1.2](LICENCE). Contributions welcome, see [`CONTRIBUTING.md`](CONTRIBUTING.md).
