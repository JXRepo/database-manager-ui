# Materials study workspace

## Delivered behavior

Collections and temporary selections now have Explore and Compare modes. Users
select two to four accessible records across pages or searches, choose a reference,
inspect 16 recorded metadata fields and open complete source metadata or curves.
The comparison separates matching, differing and incomplete rows; Differences &
gaps keeps missing or ambiguous data visible. Individual known differences remain
highlighted even when another record makes the row incomplete.

The graph focuses the selected records and their existing manual connections.
Signed return navigation preserves selection, reference order and browser state.
Native manual save/delete, failed submissions and temporary collection saves
retain that context. CSV exports the displayed bounded snapshot with source
locators, per-entry states and spreadsheet formula protection. Original JSON and
its export are unchanged.

## Review findings and corrections

- Numeric strings originally passed through floating-point normalization. Tests
  reproduced false equality for distinct decimal strings and integers above
  2^53. Comparison now validates finite numeric text without losing its original
  precision or type; quantities retain explicit units. Conflicting original
  phase/orientation parents propagate ambiguity even if normalization would make
  them look identical. Wrapped empty scalars are missing; zero/false remain valid.
- The compatibility layer reports array conflicts using one-based positions,
  while comparison schema locators are zero-based. Regression tests reproduced
  false completeness in phase/model/loading entries. Conflict positions are now
  normalized before matching, preserving each unaffected entry separately.
- Mechanical availability now keeps sample counts beside their actual components,
  includes unpaired components and identifies calculated equivalents. Conflicting
  aliases under stress/strain groups invalidate the entire output preview instead
  of selecting one alias. Missing units remain incomplete.
- Summary version 2 preparation includes absent version keys and JSON nulls on
  PostgreSQL. Only selected outdated records need preparation for comparison;
  ordinary discovery pages remain compatible with legacy summaries and omit the
  comparison payload from their member context.
- A stale manual edge could hide a native rejected draft. Failure rendering now
  clears the stale graph focus while preserving entered fields and signed study
  context. Repeated, unsigned or wrong-workspace POST navigation fails before
  mutation.
- Desktop review found an oversized initial invitation, a difficult-to-reach last
  column and an empty-state action leading to an empty browser. The invitation is
  compact, Compare opens at full available width, overflow has visible controls,
  and empty studies link directly to Search/My Data.

## Verification

Use the configured project `.venv` interpreter with DEBUG=True and synthetic data.
SQLite runs the full application regression; isolated PostgreSQL 14 on loopback
port 55439 verifies database semantics and concurrency. Chromium uses desktop
widths 1280, 1440 and 1920 with Node and the local Chart.js test bundle.

Final regression:

- Full SQLite regression: **1,116 tests**, **1,102 passed**, 14 PostgreSQL-specific
  concurrency tests skipped on SQLite. No browser tests were skipped.
- PostgreSQL integration: **137 passed**, zero skips, including concurrency,
  permissions, signed navigation, preparation/versioning and comparison semantics.
- Existing JavaScript suite: **148 passed**, zero skips.
- Django system checks, migration consistency, JavaScript syntax and whitespace
  checks pass. No migration is generated.
- Independent review reproduced the conflict-index and original-parent precision
  bugs, then retested six targeted cases after the fixes with no remaining blocker.

Commands:

```sh
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.pages apps.charts apps.dyn_api --noinput
DEBUG=True LOCAL_POSTGRES_PORT=55439 LOCAL_POSTGRES_DB=collection_test_study_release LOCAL_POSTGRES_USER=collection_test .venv/bin/python manage.py test apps.pages.test_collection_relationships apps.pages.test_collection_relationship_mutations apps.pages.test_collection_summary apps.pages.test_collection_graph apps.pages.test_collection_navigation apps.pages.test_temporary_selections apps.pages.test_study_workspace apps.pages.test_study_comparison --settings=config.settings_postgres_test --noinput
node --test tests/js/*.test.cjs
```

The new real-browser flow covers selection across pages/search, four-record limits,
reference reordering, differing/missing/ambiguous values, CSV download, source
return links, selected graph focus, invalid selection, empty collections and
long names. It also exercises manual save/delete and temporary collection save
with JavaScript disabled. Original raw data and existing annotations are checked
after browser actions. Existing collection and manual relationship browser suites
retain their layout and editing assertions.

Local evidence:

- `/tmp/study-workbench-full-tests.log`
- `/tmp/study-workbench-postgres-tests.log`
- `/tmp/study-workbench-js.log`
- `/tmp/study-workbench-qa/after/comparison-four-1440.png`
- `/tmp/study-workbench-qa/after/comparison-four-final-column-1280.png`
- `/tmp/study-workbench-qa/after/native-saved-comparison.png`
- `/tmp/study-workbench-qa/after/empty-study.png`

## Scope and release boundary

This is a domain-specific recorded-setup comparison workflow. It does not infer
scientific comparability, align phases, overlay responses, validate an ontology,
infer causal relations or export RO-Crate packages. NovaCrate's package editing
and this platform's permission-controlled cross-record study serve different
purposes; this release makes no claim of universal superiority.

No schema migration, dependency or original-data rewrite is required. Deployment
backfill upgrades cached summaries in restartable batches of 100. Local regression
establishes application behavior for a controlled pilot; it does not establish
hosted capacity, backups or persistence across redeployment. Public health and
static-asset checks do not replace authenticated hosted acceptance.

Local development backfill prepared nine outdated summaries with none remaining;
the command updated internal caches only.
