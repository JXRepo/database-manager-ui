# Charts statistics implementation plan

**Goal:** Replace the temporary Charts page with a useful, permission-aware statistics workspace.

**Authorization:** The user approved the proposed redesign and requested direct implementation, verification, commit and push without further design questions.

**Architecture:** Summarize each accessible JSON object through the shared metadata compatibility view, release raw JSON between objects, and aggregate compact summaries. Keep chart filtering, numeric bins and the paginated object list on the same server-side GET route. Render accessible HTML charts and progressively enhance panel switching with local JavaScript.

**Tech stack:** Existing Django, templates, Bootstrap theme, plain CSS and JavaScript. No new dependencies or migrations.

**Spec:** The design proposed and approved in this conversation on 2026-09-28. This file records its concrete scope and implementation contract.

## Constraints

- Desktop first at 1280, 1440 and 1920 pixels; English UI.
- Preserve original JSON, downloads, identifiers, permissions and detail plots.
- Count each object once per category; phase-level grain observations explicitly use phases as their denominator.
- Default scope is all accessible objects, with own, public and explicitly shared scopes.
- Every chart selection and object-list page rechecks access; malformed filters return no results with a clear error.
- Normalize temperature only with explicit supported units using the existing search conversion.
- Missing, malformed or conflicting values never become zero or a selected functional alias.
- Supplied equivalent arrays take precedence; calculated availability follows existing detail behavior only when absent.
- No automatic comparability claims or mixed-unit mechanical extrema.
- All comments and docstrings are English; docstring first lines have no ending period.
- User explicitly wants commits and push after verification; inspect the full diff first.

## Visual design

Use the existing Open Sans font and platform navigation. Palette: ink #18334b, blue #2862d5, teal #087f8c, canvas #f4f7fb, rule #e0e8f0, amber #946010.
Use a compact heading and scope toolbar, a single divided metrics strip, and a spacious but compact two-column category grid. A condition-distribution panel and result-availability panel sit below. The object list and data notes are expandable.
Use horizontal bars with visible counts and keyboard-focusable links. Numeric distributions use vertical columns plus explicitly labelled median and range. Empty and singleton datasets get concise factual presentations, never fabricated chart data.
Limit decoration to small colored chart accents. Use natural title case, visible focus, full-label tooltips, and text explanations for multi-label categories.

## Task 1: Accurate statistics and navigation

Files: apps/charts/analytics.py, apps/charts/views.py, apps/charts/tests.py.

Interfaces:
- summarize_object(obj) returns identity, safe display labels, category values, Decimal numeric observations, result availability and note keys. No raw arrays are retained.
- category_rows(records, field) returns full category counts with distinct-object denominators.
- distribution(records, measure) returns valid observation count, contributing object count, missing count, unit, range, median and bins with exact boundaries.
- index(request) reads scope, exact category filters, result/note filters and numeric bounds, renders charts/index.html with filtered summaries and paginated objects.
- The context exposes categories (all rows, counts, URLs), distributions (all measures), result_rows, note_rows, metrics, active_filters, clear_url, objects_page, pagination and filter_errors.

Steps:
- [x] Write behavior tests for private-data exclusion, scopes, same-record filtering and exact drill-through counts.
- [x] Write tests for multiple phases, duplicate/case-varied descriptions, wrappers, legacy labels and conflicting functional aliases.
- [x] Write tests for Kelvin/Celsius/Fahrenheit conversion, unknown units, below-zero values, phase-level grains, histogram boundaries and invalid filters.
- [x] Write tests for non-11 and equivalent-only curves, calculated provenance, unequal lengths, non-finite/bool arrays and preservation of raw JSON.
- [x] Run these tests against the old implementation and confirm failures.
- [x] Implement compact summaries, aggregate distributions, exact GET navigation and pagination.
- [x] Replace obsolete tests asserting Comparable or fixed stress_11 summaries with the new behavioral contracts.

Representative regression:

```python
response = self.client.get(reverse("charts"))
self.assertEqual(response.context["distributions"][0]["median"], "298")
self.assertEqual(response.context["total_objects"], 3)
```

The fixture contains 298 K, 24.85 Celsius and 76.73 Fahrenheit. Invalid temperatures are separate excluded observations.

## Task 2: Usable desktop page

Files: templates/charts/index.html, templates/charts/category.html, static/assets/css/charts.css, static/assets/js/charts.js, apps/charts/test_browser.py, tests/browser/charts.cjs.

Steps:
- [x] Render the heading, scope selection, compact metric strip, categorical panels, condition distributions and availability links.
- [x] Render active filters with removal links and a no-results state that preserves controls.
- [x] Show initial category rows with native expandable remaining rows, never drop categories from totals.
- [x] Keep all chart selections as ordinary GET links and the scope control as a submit form.
- [x] Add progressive keyboard-accessible switches for elastic/plastic models, loading type/mode and numeric measures; charts remain available without JavaScript.
- [x] Render a paginated object table and expandable notes with exact counts and links.
- [x] Browser-test switching, scope submission, bar selection, filter clearing, pagination, long labels and empty states.

## Task 3: Verification and delivery

Files: README.md, AGENTS.md, HANDOFF.md.

Steps:
- [x] Run apps.charts plus affected metadata/plot/CSV/navigation regression tests using the PyCharm-resolved interpreter, DEBUG=True and SQLite test databases.
- [x] Run the JavaScript suite in Chromium with zero skipped browser tests.
- [x] Inspect real desktop screenshots for empty, singleton example, varied synthetic, multi-phase and long-content datasets.
- [x] Check the supplied example without modifying or publishing it; validate 242/250-point data notes and meaningful grain/texture/temperature summaries.
- [x] Review the full diff for privacy, units, counting semantics and accidental unrelated changes.
- [x] Update project guidance and inspect the complete change.
- [x] Commit and push; report deployment separately from Git state.


## Verification evidence

- Django regression suite: 76 tests, including real HTTP Chromium navigation against isolated SQLite.
- Existing JavaScript/Chromium suite: 117 tests, zero skipped.
- Desktop checks: 1280/1440/1920 widths for varied records, long content and empty data; original example and multi-phase fixture checked separately.
- Original example: Copper / Goss, 298 K, 343 grains, 2,744 discretization count, 242–250 curve points; source checksum unchanged.
- Review regressions cover successive category/result/note/range selections, Fahrenheit bin extrema, grain aliases, invalid interval removal and close-value formatting.
- Django system checks pass; no migrations or dependencies added.
