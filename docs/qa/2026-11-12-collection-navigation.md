# Collection navigation verification

## Changes

- `apps/pages/collection_graph.py` expands small collections within an eight-object,
  25-node budget. Objects appear once even when several groups connect to them.
  Missing references default to Members unless a grouping was explicitly chosen.
- `apps/pages/collection_navigation.py` signs user-bound destinations and allowed
  group, page and presentation values. `research_collections.py` appends to the
  original collection or temporary session selection with access, deduplication
  and capacity checks. Invalid continuation requests do not create a new selection.
- Collection, Search, My Data, detail and standalone graph templates retain the
  destination through filters, Clear, object navigation and copied links. Optional
  saving is collapsed; small graphs initially fit their full viewport.
- JSON labels mean all accessible original members. Collection SVG/PNG labels
  mean the current graph page, including offscreen nodes. Single-object image
  downloads retain the complete object graph.

## Verification

All Django checks used the configured project `.venv/bin/python`, `DEBUG=True`
and local SQLite test databases. Chromium and Node with global WebSocket ran the
browser suites; no browser checks were skipped. JavaScript suite:
`node --test tests/js/*.test.cjs` — **144 passed, zero skipped**.

The full collection Chromium workflow passed at desktop widths 1280, 1440 and
1920. It exercised small, 100-object, empty and long-content collections; shared
DOI connections; metadata-only Members; same-token temporary append; direct saved
append from Search and My Data; duplicate additions; filter and Clear persistence;
group/page/view return through Details, Graph, standalone and copied links; actual
JSON/SVG/PNG downloads; CRUD; and ordinary forms/navigation without JavaScript.
Small-object cards were checked against the visible canvas bounds and inspected
in the 1280 screenshot.

Backend coverage includes tampered, repeated, foreign-user and expired navigation;
changed ownership; missing session selections; revoked object access; capacity and
whole-request rollback; empty/all-inaccessible collections; and preserved search
semantics. Existing detail metadata, mechanical plot, CSV and boundary tests also
passed in the broader regression run. The mechanical browser suite retained all
28 cases at three desktop widths.

Independent review found and verified fixes for an empty-graph exception and stale
selection recovery. Browser checks also caught stale return-view tokens, SVG link
handling during token updates, a native compact chooser URL regression, and
clipped small-collection nodes. These now have regression coverage.

Final focused run: **230 tests passed**, including both collection and standalone
graph Chromium suites, with no skipped checks. Whitespace and JavaScript syntax
checks also passed.

```bash
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test \
  apps.pages.test_collection_entries apps.pages.test_research_collections \
  apps.pages.test_collection_navigation apps.pages.test_collection_graph \
  apps.pages.test_collection_browser apps.pages.test_detail_relationships \
  apps.pages.test_my_data_filters apps.pages.test_advanced_search \
  apps.pages.test_advanced_search_engine apps.pages.test_search_capacity \
  apps.pages.test_relationship_browser --noinput
```

Local evidence: `/tmp/collection-navigation-final-tests.log`,
`/tmp/collection-navigation-regression.log`,
`/tmp/collection-navigation-followup.log`, and screenshots/downloads under
`/tmp/research-collections-navigation-qa/`. These local artifacts contain synthetic
test records and are not part of the repository.

## Scope

This change improves the existing read-only research collection workflow. It does
not add ontology mapping, scientific dependency editing or RO-Crate packaging.
Stored JSON and object permissions are unchanged. Push success alone does not
confirm a completed Render deployment.
