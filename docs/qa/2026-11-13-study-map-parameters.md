# Parameter map and detailed recorded settings

## Delivered workflow

Saved collections open their Parameter map. Supplied global temperature and
discretization count form a paged grid of exact accessible record counts.
Researchers can select a cell or an entire row, pin records across selections,
and continue into the existing comparison and result curves. Temperature units
remain separate; missing, conflicting, invalid and unsupported-unit records have
explicit coverage counts. Axis pages show eight values each; row selection covers
all horizontal pages. Empty cells indicate no visible records in this collection.

Compare now offers Inspect detailed parameters in its existing action bar. This
explicit action reads actual constitutive parameters, loading values and supplied
units. A short overview exposes differing or incomplete values, followed by an
expandable field table and signed source links. Phase, condition and array
positions retain their supplied order. Original scalar types, numeric text and
arbitrary parameter names remain distinct. Closing inspection preserves map state
and selected records without loading their complete JSON again.

No uploaded JSON, object permissions, dependencies or database models change.
Collection summary version 3 adds a small map projection; deployment backfill
prepares outdated summaries. Named saved analyses remain deferred.

## Review findings resolved

- Equivalent parent unit aliases now normalize known child spelling and scalar
  wrappers before conflict checks. The regression was reproduced before the fix.
  Independent probes retain genuine unit conflicts, different scalar types and
  decimal differences beyond binary floating-point precision.
- Map and comparison preparation share one request allowance. Incomplete
  preparation withholds the map and member browser rather than showing partial
  coverage or a misleading zero count. A three-record allowance regression checks
  the shared boundary.
- Map axis pages are canonicalized before signing source-return navigation.
  Invalid and stale cell controls fail explicitly; clearing them preserves pins.
- Deep traversal does not spend its ordinary model budget on unrelated orientation
  arrays. Duplicate phase aliases still check bounded branches for real conflicts.
- Detailed inspection uses the existing comparison action bar, preserving the
  original first-screen comparison at four records. Its closed state renders no
  parameter table and performs no raw inspection.
- Signed source navigation, manual saves, temporary selections, axis swapping,
  native forms and map selections retain the expected workspace state.

Independent whole-change review reports no remaining confirmed findings.

## Verification

Tests use the project Python environment, DEBUG=True, synthetic local records,
isolated PostgreSQL on loopback port 55439, and local Chart.js and Chromium.
Desktop browser checks cover 1280, 1440 and 1920 pixels, including native controls,
empty collections, preparation, incompatible units, exact cells, exclusions,
pinning across cells, explicit parameter inspection, source return and curves.
Original data and collection membership are compared before and after the workflow.

- Full SQLite application regression: **1,196 tests**, **1,182 passed**, 14 existing
  PostgreSQL-specific concurrency tests skipped; no browser tests skipped.
- Focused PostgreSQL regression: **139 passed**, no skips.
- JavaScript regression: **154 passed**, no skips.
- Django system checks, migration consistency and whitespace checks pass. No
  migration is required.

```sh
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.pages apps.charts apps.dyn_api --noinput
DEBUG=True LOCAL_POSTGRES_PORT=55439 LOCAL_POSTGRES_DB=collection_test_map LOCAL_POSTGRES_USER=collection_test .venv/bin/python manage.py test apps.pages.test_study_map apps.pages.test_study_details apps.pages.test_study_map_integration apps.pages.test_study_workspace apps.pages.test_collection_summary apps.pages.test_collection_navigation apps.pages.test_collection_relationships apps.pages.test_collection_relationship_mutations apps.pages.test_temporary_selections --settings=config.settings_postgres_test --noinput
node --test tests/js/*.test.cjs
```

Local evidence:

- `/tmp/study-map-full-tests-final.log`
- `/tmp/study-map-postgres-final.log`
- `/tmp/study-map-js-tests.log`
- `/tmp/study-map-qa/map-1440.png`
- `/tmp/study-map-qa/map-preparing.png`
- `/tmp/study-map-qa/map-empty.png`
- `/tmp/study-map-qa/parameters-1440.png`
- `/tmp/study-map-qa/parameters-native.png`
- `/tmp/study-map-qa/parameters-to-curves.png`

The isolated worktree initially lacked ignored assistant model assets. The full
regression was rerun after linking the existing local model revision into the
worktree; assistant production code and assets were not changed.

## Bounds and release evidence

Map aggregation reads versioned summaries. Legacy preparation retains the shared
25-record, 16-MiB and one-second boundary; incomplete work never supplies a partial
map. Separate application notification rendering retains its existing behavior.

Detailed inspection rechecks collection ownership, membership and current access
under collection and ordered object locks before loading complete selected JSON.
Temporary selections recheck the whole scope. Actual database byte lengths enforce
a 16-MiB combined allowance. Traversal limits are 300 rows, 6,000 nodes, depth 30,
32 entries per array and 512 characters per cell. Omissions are visible, retain
source links, and cannot become complete equality claims.

These are recorded-value tools: no unit conversion, inferred ontology, phase
alignment, physical comparability, causal explanation or experiment recommendation
is introduced. Public health and static-asset checks establish deployment
availability, not authenticated hosted acceptance, capacity, backups or durability.
