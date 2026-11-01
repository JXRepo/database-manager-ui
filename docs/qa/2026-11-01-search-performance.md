# Search performance verification — 2026-11-01

## Change

The previous search prefetched sharing recipients with an iterator chunk size
of one, creating a separate sharing query for every accessible object. A matching
keyword search also recognized the same JSON three times. Long numeric curves
were repeatedly walked even though their samples needed no conversion.

- `apps/pages/views.py` uses `Exists` annotations for sharing and applies the
  access scope in SQL. Keyword search and summaries reuse recognized metadata.
- `apps/dyn_api/metadata_compat.py` retains plain numeric arrays directly;
  wrappers, numeric strings and mixed arrays keep their existing handling.
- Search retains its one-record iterator and releases original payloads after
  processing. Raw storage, exports, matching semantics and permissions are unchanged.

No schema migration, dependency, production data change or UI change is required.

## Local comparison

Baseline: commit `45a91f1`. Both versions used Python 3.10.12, Django 5.2.16,
`DEBUG=True`, an isolated in-memory SQLite database and Django's test client.
The authenticated session was warmed before timing. Each case was run three
times; times below are medians, including response rendering. No profiler or
artificial network delay was used for these measurements.

Each dataset contained 105 synthetic public objects with a Copper title and
DAMASK software. The small case held approximately 0.014 MB of JSON. The curve
case added six stress and six strain arrays per object, each containing 3,000
samples (`index / 1000`), for approximately 26.08 MB of JSON. Matching searches
returned all 105 records; the unmatched keyword returned zero.

| Dataset and query | Before | After |
| --- | ---: | ---: |
| Small, Software = DAMASK | 0.0638 s | 0.0311 s |
| Small, keyword copper | 0.0630 s | 0.0298 s |
| Small, unmatched keyword | 0.0405 s | 0.0098 s |
| Curves, Software = DAMASK | 2.4642 s | 0.3490 s |
| Curves, keyword copper | 4.0528 s | 0.5046 s |
| Curves, unmatched keyword | 2.9877 s | 0.4858 s |

For all cases, Django's captured query execution count fell from 112 to 7.
This includes request overhead; initial profile creation can add queries.
The former 105 separate sharing queries are eliminated. These local counts do
not measure PostgreSQL cursor fetches or total network round trips.

## Verification

Performance regressions were reproduced before the change: 115 captured queries
for a first search of 105 objects, 24 metadata conversions for eight results,
4,170 numeric classification calls, and 4,104 recursive compatibility calls for
a 4,096-sample curve. The new regression checks pass without timing thresholds.

The tests check all access scopes, multiple sharing recipients, revocation,
private badges, unchanged storage, mixed curve samples, alias conflicts and
release of skipped and matching raw payloads.

Two existing search tests assumed that all local examples contained the same
texture, identifier, continuity flag, loading mode and temperature units. Those
failures were reproduced with the original compatibility code. Local example
checks now use each record's actual parameters for saved and default operators;
the tracked synthetic fixture still covers all 12 presets.

- All 166 targeted Django tests passed: search capacity, metadata compatibility,
  advanced search views and engine, upload compatibility and phase names.
  Django system checks passed and no model migration was detected.
- All 138 JavaScript tests passed, including Chromium controls, with no skips.
- The full Django run executed 903 tests with no skips. It reported 16 failure
  entries, including subtests. The same 16 entries were reproduced against an
  isolated archive of unchanged commit `45a91f1` using the affected test modules.
  Fourteen concern obsolete `Object n in this file` upload wording; one expects
  an old cube geometry source string; one concerns moving boundary gripping pads
  in Chromium. These existing failures remain outside this search change.
- Charts, assistant, password recovery and mechanical plot browser checks passed;
  the mechanical plot check covered 19 cases at three desktop widths.

## Remaining limits

These results do not establish authenticated production search latency. The
application still scans complete accessible JSON, including curves, rather than
a stored search index. The one-record iterator also retains PostgreSQL cursor
fetch overhead. Large datasets, database latency and Render cold starts can
therefore still slow requests. Moving file storage to Coscine alone does not
remove those costs; a future integration needs a suitable searchable metadata
store and a measured deployment architecture.

A successful push is separate from Render deployment. Live authenticated timing
must be measured separately after rollout.
