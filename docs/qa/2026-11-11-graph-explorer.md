# Graph exploration and export

The independent Graph workspace now supports node discovery and navigation,
readable inspection of large graphs, and complete image exports. It remains a
read only view of one accessible data object.

## Behavior

- Zoom buttons, actual size, fit, center, background dragging and Ctrl/Command
  wheel zoom work inside the canvas. Focus connections dims unrelated nodes
  while retaining readable zoom; Fit can then show the connected neighborhood.
- Find nodes combines complete name/detail words with a node type filter.
  Incoming and outgoing links navigate between related nodes. Stable anchors,
  browser Back and copied URLs restore the selected node; clipboard denial
  provides a selectable URL.
- Phase details include supplied texture, grain number and orientation context.
  Models include supplied parameters and model units without inferring unit
  mappings. Large containers have explicit count summaries and link to complete
  details; only the first 20 model parameter fields are previewed.
- Loading condition nodes preserve separate entries, their type, mode, targets,
  constraints and applied load count. Links to the loading panel require an
  actual supplied target, excluding the detail viewer's default free vertices.
- SVG and PNG export the complete graph, even from a focused or scrolled view.
  Standalone SVG uses plain text, escaped full names in titles and inline colors.
  PNG is limited to 8,192 pixels per side and 16 million pixels total. Original
  JSON uses the existing access checked export.
- The chooser retains the current graph while searching or paging. A current
  object outside the results is no longer inserted as an extra search result.
- Permissions, phase identity, stored JSON, full curve arrays and scientific
  plotting behavior remain unchanged. No graph database, dependency or migration
  was introduced.

## Verification

The interpreter was resolved through PyCharm. Tests used `DEBUG=True`, isolated
SQLite databases, Chromium and Node 24 with global WebSocket support:

```bash
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test \
  apps.pages.test_detail_relationships apps.pages.test_detail_metadata \
  apps.pages.test_plot_schema apps.pages.test_mechanical_csv \
  apps.pages.test_bc_schema apps.pages.test_relationship_browser \
  apps.pages.test_plot_browser --noinput

node --test tests/js/mechanical-plot.test.cjs
git diff --check
```

- 61 Django tests passed, including both real browser suites with no skips.
- 19 mechanical plot JavaScript tests passed.
- After reviewing screenshots, focus was adjusted to preserve readable zoom
  when a late phase is far from the record node. The Graph browser suite passed
  again with a regression assertion for this case.
- Browser checks cover 1280, 1440 and 1920 pixel desktop widths, long names,
  12 and 80 phases (161 nodes), text/type filtering, parameter searches, keyboard
  selection, relationship links, history, direct URLs, curve/loading links,
  zoom, fit, pan, focus, clipboard fallback, empty states and escaped HTML.
- Actual downloaded SVG is parsed and checked for all nodes, full title labels,
  no foreignObject elements and no focus dimming. Downloaded PNG signatures and
  dimensions confirm complete output, including an 8,192 pixel tall large graph.
- Native GET selection and relationship links work with JavaScript disabled.
  The existing plot browser checks cover 28 curve cases, hover, PNG and CSV at
  all three desktop widths.
- Independent code review found missing model-level units in parameter details;
  this was fixed and covered by a regression fixture. Screenshots and exported
  images in `/tmp/graph-workspace-qa/` were visually reviewed.

The pre-existing warning about an uncollected `staticfiles/` directory remains;
the browser tests serve source assets with Django's static test server.
