# Manual collection relationships

## Delivered behavior

Saved private research collections now store user-entered directed connections
between accessible members. Drag, click/keyboard selection and native forms lead
to the same explicit save operation. Names and endpoints can be changed, or a
connection deleted, without modifying uploaded JSON. Temporary selections must
be saved first. Metadata-derived connections remain read only.

Manual connections have dashed purple arrows and explicit Manual labels. The
relationship list pages 12 entries at a time; its Show / edit links focus the
selected connection and both endpoints across member pages. Ordinary graphs
render at most 100 manual edges with scope counts and distinct paths. A separate
versioned JSON export contains accessible annotations; original JSON export is
unchanged. SVG/PNG exclude editing handles and retain manual arrow styling.

## Review findings and corrections

- Real PostgreSQL threads reproduced cascading-deletion failures while a save
  inserted a relationship after cascade discovery. Collection deletion and
  single/bulk data deletion now acquire the corresponding row locks first.
- Sharing revocation originally bypassed the endpoint lock. Sharing mutations
  now acquire it, and writes recheck permission in a fresh query after waiting.
  This also closes a reproduced stale PostgreSQL snapshot when revocation wins.
- Revisions prevent stale edits/deletes. Concurrent identical creation commits
  one relationship; member removal cannot leave an annotation with a missing
  member. Read/count/export queries filter both endpoints.
- Browser inspection found gaps in dashed-line hit areas and repeated geometry
  for the thirteenth parallel edge. Continuous hit areas, distinct paths and
  nearest-curve selection keep pointer editing aligned with the intended edge;
  focused views show only the chosen manual connection.
- Unconfirmed saves retain form input and do not retry automatically. Requests
  time out after 30 seconds with guidance to check saved state. Canonical reload
  links work after native POST failures, and conflicts retain the submitted
  revision. Cancel/Escape discard an unsaved draft.

## Verification environment

Python 3.10 from the project `.venv`, DEBUG=True, local SQLite and an isolated
PostgreSQL 14 instance at loopback port 55439. Synthetic test records only.
Chromium runs at desktop widths 1280, 1440 and 1920 with Node and the local
Chart.js test bundle. No production database credentials are used.

Migration `0018_collection_relationship` adds the annotation table and its
foreign-key, no-self-link and duplicate constraints. It does not rewrite data
objects, identifiers or summaries. It applied successfully to local SQLite.

## Final verification

- Full SQLite regression: **1,084 tests**, **1,070 passed**, 14 PostgreSQL-specific
  concurrency tests skipped on SQLite. No browser test was skipped.
- Focused PostgreSQL integration: **125 passed**, zero skips, including all 14
  concurrency cases and collection/manual/single-object Chromium workflows.
- Existing JavaScript suite: **148 passed**, zero skips. Both edited graph
  scripts also pass Node syntax checks.
- Django system checks, migration consistency and `git diff --check` pass.
- Independent review reproduced and then verified the four original
  deletion/revocation races. No remaining blocker was reported.
- Browser regression includes 13 parallel links with overlapping hit areas at
  33% zoom, Compact/Detailed changes, exact keyboard selection, Escape/Cancel,
  native errors, stale edits, network failures, saved reloads and exports.

Commands:

```sh
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test apps.pages apps.charts apps.dyn_api --noinput
DEBUG=True LOCAL_POSTGRES_PORT=55439 LOCAL_POSTGRES_DB=collection_test_manual_final LOCAL_POSTGRES_USER=collection_test CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test apps.pages.test_collection_relationships apps.pages.test_collection_relationship_mutations apps.pages.test_manual_relationship_graph apps.pages.test_collection_relationship_browser apps.pages.test_collection_navigation apps.pages.test_research_collections apps.pages.test_temporary_selections apps.pages.test_collection_entries apps.pages.test_collection_summary apps.pages.test_collection_browser apps.pages.test_relationship_browser --settings=config.settings_postgres_test --noinput
node --test tests/js/*.test.cjs
```

## Operational scope

The feature supports collection-owned annotations, not ontology validation,
arbitrary RO-Crate entity editing, a shared collection editor or RO-Crate package
export. Local tests establish behavior, not hosted capacity. A Git push alone
does not prove deployment or an authenticated production editing workflow.

Local evidence files: `/tmp/manual-relationships-final-sqlite.log`,
`/tmp/manual-relationships-final-postgres.log` and `/tmp/manual-relationships-qa/`.
