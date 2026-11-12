# Collection release hardening

## Correctness changes

Temporary selections now have authoritative database buckets bound to the owner
and an HMAC of the authenticated session key. Transactions serialize updates,
including initial bucket creation and legacy adoption. Stale Django session saves
cannot overwrite the member union. Explicit creation order preserves FIFO eviction
when PostgreSQL JSONB reorders object keys. Expired buckets retain the markers needed
to prevent legacy resurrection; the maintenance command checks actual live sessions
before removing orphan buckets.

The original lost-update sequence was reproduced before the fix with two request
session snapshots: both POSTs succeeded, but the second save removed the first
addition. The corrected sequence and six genuine PostgreSQL threaded races pass,
covering parallel union, initial creation, legacy adoption, eviction and capacity
limits for temporary and saved collections.

JSONData keeps a small internal collection summary. Warm graph requests select
only summary/identity/size fields, and current access rules still constrain the
query. Save and bulk insertion refresh the projection; direct and bulk data changes
invalidate it. A stale deferred model save cannot restore an obsolete projection.
Original JSON, identifiers, record permissions and exports remain unchanged.

## Cold data and deployment

The build runs `backfill_collection_summaries --all` after migrations. It processes
a fixed initial PK range in batches of 100 and can safely resume. The migration
itself does not rewrite original data or eagerly scan existing JSON.

Web requests check at most 25 missing summaries and 16 MiB of database-verified
JSON bytes, with a one-second boundary check between records. The boundary is not
a hard timeout for a database operation. A stale underestimated size field cannot
bypass the byte check. Unknown/oversized records require operator preparation.

Pending pages report actual accessible counts (202), or an operator requirement
(503), without a partial graph or false empty state. Automatic GET continuation
stops after errors; Retry and native Continue preparing retain the workspace.
Pending GETs omit editing forms to protect drafts during automatic completion.
Rejected POSTs preserve 400 status, entered values and validation messages.

## Performance evidence

Linux, Python 3.10 and isolated local PostgreSQL 14.24; synthetic data only.
The same 1,000 objects each contain 12 mechanical arrays of 10,000 samples.
Compact original JSON totals **1,031,501,390 bytes** (about 984 MiB); collection
summaries total **361,390 bytes** (about 353 KiB).

| Measurement | Previous implementation | Summary implementation |
| --- | ---: | ---: |
| Median graph build, three runs | 15.871 s | 0.036 s |
| First measured build | 15.396 s | 0.121 s |
| Peak Python process RSS | 121.48 MiB | 67.45 MiB |
| Queries selecting raw JSON, three builds | 3 | 0 |

Cold preparation completed in 72 bounded steps. The median step was 0.349 s,
the maximum 0.459 s, and the total preparation/build work 25.334 s. These timings
exclude browser request scheduling and page rendering. Cold process peak RSS was
77.46 MiB. Warm measurements are graph-context construction, not full page latency.
These local observations do not establish Render capacity or hosting latency.

Reproduce with `tests/benchmarks/collection_graph.py` and explicit isolated
loopback settings pointing only at the `collection_benchmark` database. Run
`prepare`, then `baseline`, `current` and `cold` in separate Python processes;
the baseline source is commit `3e86b6a`. The benchmark rejects nonlocal or differently
named databases and refuses to populate a nonempty database.

## Verification evidence

The actual PostgreSQL focused regression passed **273 tests** with zero skips,
including Chromium collection and single-object graph workflows. The JavaScript
suite passed **148 tests**, zero skips. Additional focused checks cover cold-byte
guards, invalid POST status and editing-form preservation. Migration consistency
and whitespace checks pass.

The final broader SQLite run covered **1,044 tests**: 1,038 passed and the six
PostgreSQL-specific concurrency cases were skipped on SQLite. All six ran and
passed in the PostgreSQL suite above; no browser suite was skipped. This broader
run includes upload, search, detail, charts and metadata compatibility checks.
It initially exposed 15 obsolete assertion failures reproducible at the original
`3e86b6a` baseline. Only the retired upload-position wording and two cube source
expectations were maintained; identifier, access and atomicity checks were retained.
The build-script test now also requires summary preparation after migration.

Both additive migrations applied successfully to the local development database;
its nine existing records were prepared with zero missing summaries remaining.

The cold collection browser flow passed on both SQLite and PostgreSQL. It checks
202 progress to a complete graph, a native three-step GET workflow, network failure
without automatic retry, manual recovery, and the operator state without polling.
Existing collection CRUD, private/shared/public access, exact return navigation,
export scopes and three desktop widths remain covered.

Local logs: `/tmp/collection-release-final-postgres.log`,
`/tmp/collection-release-final-sqlite.log`,
`/tmp/collection-release-js-tests.log`, `/tmp/temporary-selection-before.log`,
`/tmp/temporary-selection-postgres.log`, `/tmp/collection-summary-red-proof.log`,
`/tmp/collection-summary-deferred-red.log`, and
`/tmp/collection-summary-bounded-postgres.log`. Benchmark outputs:
`/tmp/collection-benchmark-{prepare,baseline,current,cold}.log`. Browser captures:
`/tmp/research-collections-navigation-qa/`.

## Hosted verification boundary

No production database credentials or records were used for testing. Public health
requests timed out during the initial check; GitHub had no combined commit status
entries establishing a Render deployment. A successful push alone does not prove
deployment, completed migrations or authenticated production workflows. Those
states must be reported separately from the verified local PostgreSQL results.
