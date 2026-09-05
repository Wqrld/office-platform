# `clusters/demo` — the small-profile environment

## What differs from prod

Four lines. `vars.yaml` (a different domain, tenant and Gateway address), and the `path:` in
`30-platform.yaml` and `40-apps.yaml` pointing at `environments/small/` instead of
`environments/medium/`. Nothing else. There is no `apps/demo/`, no per-environment copy of
any application, and no second set of numbers to keep in step — that is the property being
protected, and it is worth re-checking whenever this directory grows a file.

## Why demo is a separate cluster and not a second namespace set on the prod node

This was the obvious cheap option and it does not work. The platform layer creates
**cluster-scoped singletons**: the `GatewayClass`-bound `Gateway`, the `ClusterIssuer`, the
`PriorityClass` set, and the ESO `ClusterSecretStore`s. A second environment on the same
cluster would have to either collide with those or grow a "share the singletons" mode —
which is a real design change to `platform/`, not a profile.

`${TENANT}` was put in every name from day one (adr/0008) precisely so this stays possible
later. It is not possible today, and the size profile is not what unlocks it.

## Does the small profile actually fit?

`config/measure.py` answers this, and the answer is recorded rather than assumed:

```
./measure.py fetch
./measure.py render environments/small/platform environments/small/apps
```

Measured (2026-09-05): **1,270m CPU / 7,426Mi of requests at install-time peak**, of which
570m/4,928Mi is the applications and 700m/2,498Mi the platform layer. Steady state, once the
migrate and superuser Jobs have finished and been collected, is **1,020m / 5,058Mi**.

The peak is the number that matters. Kubernetes admits pods on requests, and the three
Drive Jobs and two Docs Jobs each inherit `backend.resources` and run at the same time as
the workloads they are migrating for. An environment sized to the steady state will fail to
come up and look like a scheduling bug.

Add the infra layer (cert-manager, ESO, CNPG, garage-operator, Envoy Gateway, Flux itself)
at roughly 700m/1,500Mi and the floor for a working demo is about **2 cores and 9Gi**.
