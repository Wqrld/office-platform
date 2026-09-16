# 0110 — the object store is published, scoped to one bucket

**Status:** accepted · **Date:** 2026-09-03 · **Amends:** design set `06-datastores.md`

## Context
Docs never exposes the object store. Attachments are *downloaded* through our media proxy,
which signs server-side and talks to Garage over cluster DNS, and uploads go through Django.
Garage has no public address and does not need one. `06-datastores.md` states that as a
property of the platform.

Drive uploads differently. `core/api/utils.generate_upload_policy` returns a **presigned PUT
URL** and the browser uploads the file body straight to the object store. Upstream comments
on the function say this is deliberate: it keeps large bodies off the Django workers.

A presigned URL's signature covers the host, so the URL has to be signed against the host
the browser will use. That is exactly what Drive's `AWS_S3_DOMAIN_REPLACE` is for. Without a
publicly reachable object store there is no value to put in it and file upload does not
work at all — there is no in-application fallback.

## Decision
Publish the Garage S3 API at `s3.<baseDomain>` through the shared Gateway, and restrict that
route to the paths of the buckets that need it. Today that is one prefix, `/drive/`.

- One `HTTPRoute` in `office-data`, `PathPrefix: /drive/` only. `office-data` gains the
  `gateway-access` label; nothing else in it is routed.
- Addressing is **path-style**, so a bucket is a path prefix and the route is a real bound:
  a request for `/docs/...` on the public endpoint matches no route and 404s at the edge,
  before Garage sees it. Verified that botocore presigns path-style against a custom
  `endpoint_url`.
- CORS is a `SecurityPolicy` on that route, `allowOrigins: https://drive.<baseDomain>`.
  Garage's own bucket CORS config is not reachable through the operator's CRDs, and doing it
  at the edge keeps the rule next to the route it belongs to.
- No `requestBuffer`: uploads stream. Buffering a multi-gigabyte body in Envoy to enforce a
  limit Drive already enforces (`DATA_UPLOAD_MAX_MEMORY_SIZE`) trades an upload for an OOM.

## What this does and does not expose
An unsigned request to the public endpoint is rejected by Garage exactly as it is on the
internal one — the endpoint is not an authorisation boundary and never was. What changes is
that the SigV4 surface is now reachable from the internet for one bucket.

The presigned URLs themselves are narrow by construction: one method, one key, and
`AWS_S3_UPLOAD_POLICY_EXPIRATION` is 60 seconds by default. They are also `PUT`-only, so a
leaked upload URL cannot read anything back.

The `/docs/` bucket stays unreachable from outside, which is the property this route's
scoping is there to keep true. **Adding a bucket to that route is a security decision**, not
a routing tweak.

## Consequences
- `s3.<baseDomain>` joins the SAN certificate and must resolve to the Gateway before it is
  added, like every other name — `adr/0105`.
- `platform-deps` grows an `objectstore.publicEndpoint` value and the profiles grow a
  `publicEndpoint` concept. It is empty by default and stays empty for every app that does
  not presign to the browser.
- If a second app ever needs this, extend the route's paths and the CORS origins in the same
  commit, and say in the message which bucket became internet-reachable.
