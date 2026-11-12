# Research Collections Implementation Plan

> **For agentic workers:** Execute the independent backend, graph and entry tasks
> in parallel, then integrate, verify and review the complete workflow.

**Goal:** Make multiple accessible simulation records explorable and manageable
as named research collections.

**Architecture:** Add collection membership beside unchanged JSONData records.
Use Django session selections, permission-filtered queries and server-rendered
graph summaries; reuse the existing graph renderer and native form navigation.

**Tech Stack:** Django, Django templates, existing Bootstrap, plain JavaScript,
SQLite for local verification. No new dependencies.

**Spec:** ../specs/2026-11-12-research-collections-design.md

## Global constraints

- English application text; concise Chinese user updates.
- Original data and export values remain unchanged.
- Collections are private to their owner; member access is always checked.
- Maximum 500 objects per temporary selection, 1,000 per saved collection.
- Group and object pages contain 25 entries.
- Use DEBUG=True with the configured .venv/bin/python, never production DB.
- Preserve existing graph deep links, search, exports and detail visualizations.

## Review focus

- Revoked access must disappear from graph labels, counts and exports.
- Mixed valid/invalid selection must fail without partial collection writes.
- Identical labels must not imply identical scientific entities.
- Long titles, 100+ records and missing metadata must remain navigable.
- No-JavaScript forms and graph links must still complete the workflow.

## Task 1: Persistence and views

Files: apps/pages/models.py, migrations, research_collections.py and
test_research_collections.py.

Interface: ResearchCollection(owner, title, description, members, timestamps),
accessible_objects(user), collection_index/detail/update/remove/delete/export,
selection_create/detail/export, collection_save/add. Temporary POST forms use
selected_objects; collection forms use title, description and collection_id.

- [x] Test selection validation, ownership, all object permission modes,
  permission revocation, atomic save/add/remove, limits and deletion isolation.
- [x] Implement session selections, private collections and guarded mutations.
- [x] Run DEBUG=True .venv/bin/python manage.py test
  apps.pages.test_research_collections --noinput; expect all tests to pass.

## Task 2: Cross-object graph

Files: apps/pages/collection_graph.py, test_collection_graph.py and the existing
detail_relationships renderer template, CSS and JavaScript.

Interface: build_collection_context(accessible_queryset, *, title, base_url,
params) returns relationship_graph, dimension/group navigation, accessible
counts and paginated object_rows. Query keys are links, group, page,
groups_page and view. Invalid selection dimensions raise ValueError.

- [x] Test declared relations, metadata compatibility, duplicates, missing
  metadata, immutable input, malformed selectors and bounded 100-record graphs.
- [x] Implement summary extraction and bounded graph layouts; generalize
  renderer source links and export names without changing single-object use.
- [x] Run DEBUG=True .venv/bin/python manage.py test
  apps.pages.test_collection_graph apps.pages.test_detail_relationships --noinput;
  expect all tests to pass after entry integration.

## Task 3: Entries and workspace integration

Files: templates/pages/search.html, data_list.html, data_detail.html,
collections.html, collection_graph.html; static/assets/css/research-collections.css;
apps/pages/views.py, urls.py, graph.py; templates/includes/sidebar.html.

- [x] Add graph_selection_create action using existing selection forms.
- [x] Add Details/Graph navigation at ?tab=graph and preserve standalone links.
- [x] Add collection index, create/add/edit/remove forms, graph dimensions and
  member comparison table with ordinary native navigation.
- [x] Test entries and run node --test tests/js/*.test.cjs; expect no failures.

## Task 4: Browser verification, review and delivery

Files: apps/pages/test_collection_browser.py, tests/browser/collections.cjs,
README.md, AGENTS.md and docs/qa/2026-11-12-research-collections.md.

- [x] Verify actual selection/save/add/explore/edit/remove/delete flows,
  graph detail drilldown, empty/long/large content, desktop widths and no JS.
- [x] Run graph, search, My Data, detail and plot regression tests, including
  actual Chromium tests; skipped browsers do not count as verified.
- [x] Request an independent review; fix material findings and run affected
  checks. Inspect final diff and migration consistency.
- Delivery: commit and push authorized changes; distinguish push from deployment.

## Execution record

Implementation and verification are complete. The final combined Django run
passed 255 tests, including all three actual Chromium suites; JavaScript checks
passed 144 tests with no skips. All independent review findings were addressed
with regression coverage. The review added explicit unavailable-member cleanup
to avoid permanently exhausting collection capacity after access revocation.
See `docs/qa/2026-11-12-research-collections.md` for evidence and scope boundaries.
