# Research collections verification

## Delivered workflow

Search and My Data can open selected records in Graph, save a private named
collection, or add them to an existing collection. Collections support editing,
member removal, explicit cleanup of unavailable references and deletion without
deleting data. Graph offers declared references, reported software and phase
name groups, and collection members. Each group and member page contains at most
25 entries; the comparison table and detail Graph tab provide object drilldown.

Implementation entry points:

- `apps/pages/research_collections.py`: guarded session selections, collection
  management and original JSON downloads.
- `apps/pages/collection_graph.py`: access-scoped summaries, explicit references,
  named metadata groups and bounded layouts.
- `apps/pages/models.py` and migration `0015_researchcollection.py`: independent
  collection membership, leaving stored JSON and record permissions unchanged.
- `templates/pages/collections.html`, `collection_graph.html` and shared
  `detail_relationships.html`: collection workspace and reusable graph renderer.
- Search, My Data and data detail templates: selection actions and local
  Details / Graph navigation. Existing standalone graph URLs remain supported.

## Verification results

Configured interpreter: this computer's `.venv/bin/python` (Python 3.10).
All Django runs used `DEBUG=True` and local SQLite test databases.

```bash
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test \
  apps.pages.test_collection_entries apps.pages.test_research_collections \
  apps.pages.test_collection_graph apps.pages.test_collection_browser \
  apps.pages.test_detail_relationships apps.pages.test_detail_metadata \
  apps.pages.test_plot_schema apps.pages.test_mechanical_csv apps.pages.test_bc_schema \
  apps.pages.test_my_data_filters apps.pages.test_advanced_search \
  apps.pages.test_advanced_search_engine apps.pages.test_search_capacity \
  apps.pages.test_relationship_browser apps.pages.test_plot_browser --noinput
```

Result: **255 tests passed**, including all three actual Chromium suites, with
no skipped browser checks. `node --test tests/js/*.test.cjs`: **144 passed,
0 skipped**. Migration consistency check reported no pending model changes;
the additive migration applied successfully to the local development database.

The collection browser test exercised real checkboxes and form submissions:
selection, save, reopen, grouped exploration, object detail Graph, copied links,
append, edit, remove and delete. It verified 100 accessible members including
owned, public and explicitly shared data, excluded a revoked member from counts
and downloads, downloaded actual SVG/PNG/JSON, and compared original records
after the workflow. Native forms and navigation also passed without JavaScript.

Desktop widths: 1280, 1440 and 1920 pixels. Long collection descriptions, long
object titles, missing metadata, multiple group/member pages and empty collections
remained usable without page overflow. Existing graph behavior and all 28
mechanical plot browser cases retained their prior checks.

Local screenshots and downloads: `/tmp/research-collections-qa/`, including
`selected-two-objects.png`, `saved-collection.png`, `object-graph-tab.png`, and
the desktop and empty-state captures. Final test log:
`/tmp/research-collections-final-tests.log`.

## Independent review and fixes

An independent agent reviewed permissions, mutations, metadata interpretation,
native navigation and error recovery. Its concrete findings were addressed:

- An invalid or expired group now gives a direct overview link and does not
  mislabel the collection as empty. Reproduction failed before the fix and passed
  afterward for both saved and temporary workspaces.
- Numeric software versions, including 0 and 3.0, remain visible in comparison
  rows and node details. The raw JSON is unchanged.
- Encoded DOI resolver paths are decoded once, with invalid encodings retained
  as literal references, avoiding an incorrect split of equivalent DOI forms.
- Success messages appear on the action's destination and are consumed there,
  rather than surfacing on a later Search visit.
- An explicit owner-only POST can clear unavailable member references and free
  capacity. It does not expose hidden names or counts, delete records, or alter
  access. Tests cover a full 1,000-member collection, retained accessible members,
  foreign ownership, CSRF and method restrictions.

Every fix has a regression test; no material review finding remains deferred.

## Scope

Collections are currently private to their owner. They organize references and
metadata labels; they do not establish scientific dependencies. RO-Crate
packaging, collection sharing, hosted input/output files and relation editing
remain separate future features. Single-object images export the complete graph;
collection images explicitly export the current graph page and view. The existing
Render build script runs migrations, but a successful Git push does not establish
that a deployment has finished.
