# Candidate discovery and recorded result curves

## Delivered workflow

The first pinned record is the reference. Find comparison candidates searches
only currently accessible members of the collection or temporary selection.
Researchers select fields that must match and a distinct field that must differ.
Each result exposes the recorded values behind the decision; incomplete data is
separate from a known match or contradiction. Results are paged and preserve the
reference when opened directly in Compare or added to its pins.

Result curves loads actual arrays only when the researcher opens it. Two to four
records can be inspected beside their settings, with explicit component and
total/plastic strain controls. Individual panels explain their independent scales.
An explicit overlay uses shared scales and is enabled only for recognized matching
units and complete requested pairs. Curve focus highlights the corresponding pin
and settings column. Hover and keyboard inspection select a real recorded sample;
loops, signs, source indices, unequal tails and calculated-equivalent origins stay
visible. Native forms and signed source links remain available without JavaScript.

No schema migration, dependency, object-permission change or uploaded-data rewrite
is introduced. The existing detail plots and Charts remain separate from these
comparison panels.

## Review findings resolved

- All graph, selected comparison and candidate preparation stages now share one
  request budget. A regression with a three-record allowance confirms that the
  complete request prepares only three records and withholds partial candidate
  classifications until the whole accessible scope is ready.
- Native checkbox criteria use an explicit empty sentinel, distinguishing an
  intentional clear-all error from the initial default criteria. Invalid criteria
  retain the valid reference and a correctable native form.
- Curve limits count paired samples, rather than rejecting valid curves solely
  because an unpaired tail is longer. Equivalent calculations receive only the
  paired source slices while retaining the complete available source counts.
- Equivalent scalar/object wrappers in duplicate known aliases no longer produce
  false conflicts. Independent probes confirm that different high-precision
  original values and different array lengths still remain ambiguous, and that
  raw JSON is unchanged.
- Candidate pages clamp to the available range in both direct links and signed
  return state. An initially failing regression reproduced the stale signed page
  before the fix and now passes through a real source-detail return.
- Desktop inspection added explicit independent/shared scale guidance and actual
  mathematical subscripts. A loaded-font probe measured the longest tested
  scientific endpoint at 57.96 pixels within its 68-pixel allowance.

## Verification

Tests use the project `.venv` interpreter, DEBUG=True and synthetic local records.
The PostgreSQL instance is isolated on loopback port 55439. Chromium checks use a
local Chart.js bundle and desktop widths 1280, 1440 and 1920.

The new browser workflow covers candidate evidence and uncertainty, 25-entry
pagination, clear-all errors and recovery, candidate-to-comparison navigation,
lazy curve requests, full cyclic paths, sample hover and keyboard controls,
linked settings, four-record overlays, incompatible units, missing curves,
explicit retries, temporary selections, signed source return and native controls.
It also verifies that original JSON and collection membership stay unchanged.

Final results:

- Full SQLite regression: **1,149 tests**, **1,135 passed**, 14 existing
  PostgreSQL-specific concurrency tests skipped on SQLite; no browser tests skipped.
- PostgreSQL integration: **126 passed**, zero skips.
- JavaScript suite: **154 passed**, zero skips.
- After the final signed-page correction, a further **32 workspace/navigation
  tests passed** on SQLite and **6 integration tests passed** on PostgreSQL.
- Independent review has no remaining confirmed findings. Django system checks,
  migration consistency and whitespace checks pass; no migration is required.

```sh
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.pages apps.charts apps.dyn_api --noinput
DEBUG=True LOCAL_POSTGRES_PORT=55439 LOCAL_POSTGRES_DB=collection_test_discovery LOCAL_POSTGRES_USER=collection_test .venv/bin/python manage.py test apps.pages.test_study_candidates apps.pages.test_study_curves apps.pages.test_study_discovery apps.pages.test_study_workspace apps.pages.test_collection_summary apps.pages.test_collection_navigation apps.pages.test_collection_relationships apps.pages.test_collection_relationship_mutations apps.pages.test_temporary_selections --settings=config.settings_postgres_test --noinput
node --test tests/js/*.test.cjs
```

Local evidence:

- `/tmp/study-discovery-full-tests-final.log`
- `/tmp/study-discovery-postgres-final.log`
- `/tmp/study-discovery-js-tests-final.log`
- `/tmp/study-discovery-navigation-final.log`
- `/tmp/study-discovery-browser.log`
- `/tmp/study-discovery-qa/candidates-1280.png`
- `/tmp/study-discovery-qa/curves-pair-1440.png`
- `/tmp/study-discovery-qa/curves-cyclic-component.png`
- `/tmp/study-discovery-qa/curves-unit-mismatch.png`
- `/tmp/study-discovery-qa/curves-native-controls.png`

## Limits and release boundary

Candidate equality applies only to selected complete recorded fields. Matching
names do not establish scientific equivalence, and this feature does not claim
that every other simulation setting is identical. There is no inferred ontology,
causality, curve alignment, interpolation, unit conversion or material-property fit.

Warm candidate searches read bounded cached summaries. Preparation retains the
existing 25-record, 16-MiB and one-second request boundary. Curve requests check
current permissions and membership before reading raw records, enforce 16 MiB of
actual stored JSON and 100,000 paired samples per selection, and reject excessive
requests without a partial preview. Source details remain available for larger
records. Curve responses are private and non-cacheable.

Local application and browser verification establish behavior for a controlled
pilot. Public health, route and static-asset checks cannot establish authenticated
hosted workflows, hosting capacity, backups or persistence across redeployment.
