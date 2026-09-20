# Object storage — Garage

S3 for Docs, Drive and Meet. One cluster; the bucket and scoped key are emitted by
`platform-deps` in the app's namespace, the grant that lets them reach the cluster by
`platform-tenants`.

## Why an operator for one bucket

The operator is **control-plane only**: it calls Garage's Admin API to create buckets and
keys. Garage holds the data. If `rajsinghtech/garage-operator` (Apache-2.0, active, but a
single maintainer) stalls, what is lost is declarative bucket management — not documents —
and the replacement is a Job, which is *more* of our own code than the operator is.

That bounded blast radius is the whole reason this is acceptable under P6.

## The credentials contract, without an extra hop

`GarageKey.secretTemplate` writes the canonical `objectstore` key set from `history/design/06-datastores.md`
directly — `endpoint`, `region`, `bucket`, `accessKeyId`, `secretAccessKey` — so no ESO
`ExternalSecret` is needed to reshape it. Applications still only ever see a Secret with
those keys and never learn what Garage is (P4).

## Decisions that are expensive to revisit

- **`replication.factor: 1` cannot be changed in place.** Raising it requires destroying and
  rebuilding the cluster. One node, one copy.
- **No node-local storage pools.** They require `privileged` Pod Security Admission, which
  contradicts the security baseline. PVC-backed only.
- **No multi-cluster federation.** It needs externally routable per-node RPC addresses and we
  have no requirement for it (P6).
- **Checksums.** AWS SDKs since 2025 send checksum algorithms Garage rejects; verified, and
  `platform-deps` sets `AWS_*_CHECKSUM_*=WHEN_REQUIRED` in every S3 Secret
  (`objectstore.awsChecksumWorkaround`, on by default).

## Delete order matters — verified the hard way

The operator **refuses to delete a non-empty bucket** (`BucketNotEmpty`, 409) and never empties
one automatically. That is the right behaviour, but it means:

**Empty the bucket BEFORE deleting its GarageKey.** Delete the key first and you strand the
bucket in `Deleting` forever, with no credentials left to empty it. Recovery is to create a
temporary `GarageKey` with `allBuckets: {owner: true}`, empty the bucket, then delete both.

Set `deletionPolicy: Retain` on any bucket whose contents should outlive its CR.

## Retention is not configured

The bucket carries a quota and nothing else. Nothing here decides whether Docs' orphaned
media is ever deleted. That is an application-level retention question, and an unbounded
bucket behind a quota is an outage with a date on it.
