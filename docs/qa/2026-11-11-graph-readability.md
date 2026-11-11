# Graph entry and readable relationship cards

## Result

The Graph entry is one search and record list. Each result opens directly,
pagination stays bounded to 25 records, and the list scrolls within the panel.
The duplicate selection card, dropdown and oversized welcome panel are gone.
The current graph stays open while choosing another record.

Incoming relationships are visible at the card headers where their arrows
arrive. Compact cards show the relationship and complete accessible name;
Detailed cards add up to three supplied fields, prioritizing explicit model
units. Names and previews are visually bounded, with full text available in
titles and the inspector. Card heights follow supplied content, without missing
field placeholders. Existing site fonts, colors and desktop layout are retained.

Both presentations share server-generated geometry and stable node identities.
JavaScript switches views immediately and preserves the selected node, including
through browser history, chooser searches and copied links. Native record and
view links work without scripts. Detailed inspection starts at 100% or greater;
Fit remains available for a complete overview.

SVG and PNG export the complete chosen layout, regardless of the viewport or
connection focus. Relationship labels and field previews use portable SVG text,
and filenames identify the presentation. PNG captures dimensions and mode at
the start of export and retains the existing pixel limits. Original JSON,
permissions, phase identities and curve calculations remain unchanged.

## Verification

The configured PyCharm interpreter was used with `DEBUG=True`, SQLite test
databases, Chromium and Node 24:

```bash
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test \
  apps.pages.test_detail_relationships apps.pages.test_detail_metadata \
  apps.pages.test_plot_schema apps.pages.test_mechanical_csv \
  apps.pages.test_bc_schema apps.pages.test_relationship_browser \
  apps.pages.test_plot_browser --noinput

node --test tests/js/mechanical-plot.test.cjs
git diff --check
```

- 63 Django tests passed, including both browser suites without skips.
- 19 mechanical plot JavaScript tests passed.
- Graph checks cover a 109-record chooser, 25-row pages, direct opening,
  search and pagination, retained graph/node/view state, and empty results.
- Compact and Detailed layouts were checked at 1280, 1440 and 1920 pixel desktop
  widths, with measured name, relation and preview bounds. Cases include long
  names, empty metadata, 12 phases and 80 phases (161 nodes).
- All five existing JSON examples in
  `example_json_files/boundary_condition_examples_20261008/` were opened and
  inspected in Detailed mode. These are the repository's labelled synthetic
  references, not experimental measurements.
- Actual SVG downloads were parsed and checked for complete node sets, relation
  labels, parameter values, units, portable text and expanded geometry. PNG
  signatures and dimensions were checked in both modes and for a large graph.
- Native search, record opening, node links and Detailed view work with
  JavaScript disabled. Existing plot hover, full PNG and CSV checks also pass.
- Independent review found no Critical or Important issues. Its documentation
  suggestion is included in README and AGENTS.md.

Screenshots and exported images were visually inspected in
`/tmp/graph-workspace-qa/`, including `picker-1440.png`, `detailed-1440.png` and
`example-01_point_tension_aluminium.png`. The existing uncollected `staticfiles/`
warning remains; the browser tests serve source assets directly.
