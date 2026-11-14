# Difference navigation and saved analyses

## Delivered workflow

Detailed inspection now offers All fields, Differences and Incomplete filters,
field/path search, exact field focus from summary cards, visible result counts,
empty-result recovery and fixed field/reference columns. JavaScript filters the
existing bounded table immediately. Native GET links and forms retain the same
controls and source-return state.

A compact Save analysis panel stores two to four ordered record references,
workspace choices and the user's own name and notes in a private collection.
Saved analyses reopen the complete selection, preserve map/candidate/detail/curve
choices, and distinguish unsaved edits and changed source JSON. Save changes,
Save as new and Delete are explicit operations. Notes remain editable after
validation errors or stale revisions. An unconfirmed response never automatically
retries a mutation. Actual unsaved text has browser leave protection; presentation
changes alone do not trigger that warning.

Migration `0019_savedstudyanalysis` adds an independent table. Deleting an analysis
does not alter collection membership or source records. Existing detail plots,
uploaded JSON and original exports are unchanged by this feature.

## Review findings resolved

- Lazily generated curve cards now read live signed source links, retaining the
  latest field filters even when navigation synchronization finishes before the
  curve request. Browser regression follows the card's Source link and returns.
- Saved state is assembled after manual relationship pagination; native detail
  filters preserve that page as well. Regression saves and restores page 2 with
  13 relationships.
- Native error rendering reuses validated state instead of reparsing malformed
  deeply nested JSON. The rejection preserves entered notes without a 500 or a
  mutation to saved analyses or original data.
- Signed navigation uses bounded compressed tokens and a consistent 32-KiB read
  limit. A maximal multibyte-search test checks refreshed and uncompressed tokens.
- Native name/notes validation errors retain valid pins, active identity and
  revision, allowing correction and resubmission. Invalid state still fails closed
  and foreign analysis identities are not restored.
- Analysis form IDs are unique beside the existing collection form, so labels
  target the intended controls. Compact spacing preserves first-screen comparison
  visibility for four records on desktop.
- Source digests check actual combined JSON bytes before hashing. Unavailable
  source identities are omitted from saved baseline and failure HTML. Opening is
  read-only; only an explicit successful update accepts a new source baseline.

Independent review reports no outstanding findings. Three PostgreSQL concurrency
tests cover the last free analysis slot, stale update/delete after waiting for a
collection lock, and access revocation winning the object lock before a save.

## Verification

Tests use the project Python environment and synthetic records. Browser workflows
run in Chromium at 1280, 1440 and 1920 pixels, with local Chart.js. They cover
four-record scrolling, filters, exact focus, source navigation, lazy curves,
overlay/open persistence, create/update/copy/delete, a true revision conflict,
unconfirmed-save recovery, changed/unavailable sources, 12-entry pagination,
temporary-selection guidance and JavaScript-disabled controls.

Application verification before integrating independent plot changes:

- SQLite regression: **1,239 tests**, **1,222 passed**, 17 PostgreSQL-specific
  concurrency checks skipped. No browser tests were skipped.
- PostgreSQL integration and concurrency regression: **143 passed**, no skips.
- JavaScript regression: **154 passed**, no skips.
- Django checks and migration consistency pass; migration 0019 is the only new
  schema change. Whitespace checks pass.

After integrating the separate plot-placement change `23386e9`, another **11
browser/navigation tests** and the updated **157-test JavaScript suite** passed.
The detail-plot implementation and its tests remain identical to that commit.

```sh
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.pages apps.charts apps.dyn_api --noinput
DEBUG=True LOCAL_POSTGRES_PORT=55439 LOCAL_POSTGRES_DB=collection_test_analysis_final LOCAL_POSTGRES_USER=collection_test .venv/bin/python manage.py test apps.pages.test_study_analyses apps.pages.test_study_navigation apps.pages.test_study_detail_navigation apps.pages.test_study_details apps.pages.test_study_map_integration apps.pages.test_study_workspace apps.pages.test_collection_navigation apps.pages.test_collection_relationships apps.pages.test_collection_relationship_mutations apps.pages.test_temporary_selections --settings=config.settings_postgres_test --noinput
node --test tests/js/*.test.cjs
```

Local evidence:

- `/tmp/study-analysis-full-tests-final.log`
- `/tmp/study-analysis-postgres-final.log`
- `/tmp/study-analysis-js-tests-final.log`
- `/tmp/study-analysis-merged-browser.log`
- `/tmp/study-analysis-merged-js.log`
- `/tmp/study-analysis-browser-final.log`
- `/tmp/study-analysis-browser-layout.log`
- `/tmp/study-analyses-review-final.log`
- `/tmp/study-analysis-signing.log`
- `/tmp/study-analysis-qa/analysis-editor-1440.png`
- `/tmp/study-analysis-qa/differences-1280.png`
- `/tmp/study-analysis-qa/source-changed.png`
- `/tmp/study-analysis-qa/stale-revision-notes.png`
- `/tmp/study-analysis-qa/unconfirmed-save.png`
- `/tmp/study-analysis-qa/native-saved-analysis.png`

## Limits and release boundary

Collection ownership and current source access remain authoritative. Analyses
require two to four accessible current members, signed POST scope and CSRF;
collection and ordered object locks serialize final checks. Existing revisions
must match for update/delete. Names are at most 120 characters on one line,
notes 5,000, state 16 KiB, and source JSON 16 MiB combined before database hashing.
Collections hold at most 100 analyses, listed 12 per page. Digests detect stored
JSON changes; they do not establish scientific identity or comparability.

No inferred ontology, causal conclusions, unit conversion or material-property
estimation is introduced. Existing detailed-inspection limits and explicit
omission messages continue to apply. Source data is never copied into an analysis.

The deployment script applies the additive migration and collects new assets.
Public health and asset checks establish availability of the release; they do not
establish authenticated hosted acceptance, storage durability, backups or capacity.
