# Collection correctness and capacity

The user approved fixing the production-readiness gaps identified in review:
concurrent temporary-selection updates, repeated raw-JSON reads for collection
graphs, and missing PostgreSQL and deployment verification.

## Design

Temporary selections keep their existing URLs and user-visible workflow. Store
their authoritative member lists in one database bucket per owner and authenticated
session, identified by an HMAC of the session key. Serialize explicit updates with
a transaction and lock; retain the eight-selection and 500-object limits. A bucket
adopts legacy session entries once on an explicit POST. Existing bucket state wins
over stale session snapshots, including after eviction or expiry. GET requests do
not change selection membership. Bind lifetime to the session and cap inactivity.

Store the existing scalar and grouping summaries in a nullable internal JSONData
field. Warm graph requests load these summaries without mechanical arrays. Normal
saves and bulk creation generate summaries, while raw-data updates invalidate
them. Fill legacy missing summaries individually under a transaction and recheck
access; avoid a large data-rewrite migration. Grouping semantics, original JSON,
exports and access control stay unchanged.

Deployment prewarms a fixed snapshot of existing records after additive migrations.
The web fallback also enforces a 25-record, 16-MiB verified-byte budget and a time
boundary between records. Pending requests expose actual ready/total counts and
never a partial graph; unknown or oversized records require operator preparation.
Automatic continuation stops on connection failure, while native GET continuation
remains available. Editing forms stay hidden during automatic preparation so a
completion redirect cannot discard a draft; failed POST forms keep their errors.

## Alternatives considered

- Retaining authoritative membership in Django sessions leaves unrelated session
  responses able to overwrite a corrected list. A separate locked bucket avoids
  that failure and handles legacy entry eviction without per-token tombstones.
- An in-process summary cache is lost on restart and duplicated across workers.
  Persisting the projection makes normal requests independent of raw array size.
- Eagerly rebuilding every old object's summary during deployment could stall
  migrations. Nullable summaries allow incremental filling and an operator command.

These implementation choices follow the approved fixes and preserve the existing
interface. No ontology mapping, new visualization feature or permission expansion
is included.

## Evidence required

Reproduce the stale-session update failure, run actual concurrent requests against
isolated PostgreSQL, test capacity and permission rejection, verify summary
invalidation and raw-data exclusion in warm queries, and measure a 1,000-object
synthetic collection with long mechanical arrays. Retain browser regression
coverage. Check the public deployment without modifying production records and
report any missing authenticated or hosting evidence explicitly.
