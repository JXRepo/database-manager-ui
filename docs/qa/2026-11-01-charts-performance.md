# Charts performance verification — 2026-11-01

## Change

`apps/charts/analytics.py` previously passed every recognized mechanical curve
sample through `number()`, which converted it to text, then Decimal, then float.
Charts needs sample validity and series lengths, not those converted values.
Profiling 105 synthetic objects found 3,780,315 calls to `number()`; curve
availability accounted for 5.13 of 5.75 seconds under the profiler.

Availability now checks numeric type and finiteness directly. It still examines
every sample and rejects booleans, nonnumeric values, nonfinite floats and integers
that overflow float conversion. Series lengths, matching components, supplied
and calculated equivalent availability, and notes retain their existing rules.
Temperature, count and distribution calculations still use exact Decimal values.

The database query, permission scopes, metadata compatibility view, raw JSON,
exports and charts are unchanged. No dependency or migration is needed.

## Local comparison

Baseline: commit `352f5a9`. Both versions used Python 3.10.12, Django 5.2.16,
`DEBUG=True`, isolated SQLite in memory and the authenticated Django test client.
The session and empty Charts page were warmed before timing. Each measurement
below is the median of three requests, including response rendering, without
a profiler or artificial network latency.

Both datasets contain 105 synthetic public objects with Copper phase, DAMASK
software, Goss texture, grain count 343, temperature 298 K, discretization count
2744 and a stress/static loading pair. The curve dataset adds six stress and six
total strain arrays per object, each with 3,000 samples (`index / 1000`). It holds
approximately 26.106 MB of JSON and all 105 objects have matching components.

| Dataset | Before | After |
| --- | ---: | ---: |
| Small metadata, no mechanical arrays | 0.0159 s | 0.0152 s |
| Six stress and six strain arrays per object | 2.4008 s | 0.6628 s |

The curve case uses about 72% less elapsed time. Captured query execution counts
remain eight per request. This measures local application work, not production
latency; remote JSON transfer, PostgreSQL cursor fetches and hosting startup can
still add time. Charts continues to scan the current scoped objects on each visit.

## Verification

- The existing large-array regression test first failed with 24,008 numeric
  conversions; it now passes with a budget below 100 calls, independent of timing.
- Numeric edge cases cover large finite integers, overflow, tiny finite floats,
  infinities, NaN, booleans and malformed final samples after 4,096 valid values.
- All 60 tests in `apps.charts` passed, including the Chromium browser test with
  no skips. Checks cover public/private scopes, statistics, original precision and
  stored JSON, legacy filters, exact numeric intervals and object navigation.
- Browser checks passed at desktop widths of 1280, 1440 and 1920 pixels, including
  long and empty content, tooltips, keyboard operation and no-JavaScript behavior.
- Django system checks and `git diff --check` passed.

Command: `DEBUG=True CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.charts`
