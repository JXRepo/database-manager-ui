# Independent Graph workspace

## Placement and behavior

Graph now has a sidebar entry beside Charts and its own `/graph/` page. The
detail header's Open in Graph link supplies the current object. The workspace
keeps the graph open, puts node information on the right, and shows the selected
record and View data details link above the canvas. The earlier embedded detail
panel has been removed.

Change data opens a selector with 25 records per page and a title or identifier
search using the existing whole word matcher. Browsing choices retains the
current graph until selection is submitted. Without a query, the database
paginates before JSON is read. Searches retain only short label summaries and
release each record's JSON as they progress.

Both the selector and selected object query enforce owner, public and explicit
share access. The page requires sign in. Invalid and repeated object arguments
return a clear 400 response, and inaccessible or missing records return 404.
No record is selected automatically. Existing graph extraction, original JSON,
phase to model relationships, output summaries and exports are retained.

## Verification

The configured project interpreter was resolved through PyCharm. Checks used
`DEBUG=True`, isolated SQLite test databases, Chromium and Node 24:

```bash
DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test \
  apps.pages.test_detail_relationships apps.pages.test_detail_metadata \
  apps.pages.test_plot_schema apps.pages.test_mechanical_csv \
  apps.pages.test_bc_schema apps.pages.test_relationship_browser \
  apps.pages.test_plot_browser --noinput

node --test tests/js/mechanical-plot.test.cjs
git diff --check
```

- 58 Django tests passed, including two browser tests without skips.
- 19 mechanical plot JavaScript tests passed.
- Graph browser checks cover detail and sidebar entry, preserved object context,
  return to details, search, changing data, keyboard node selection and ordinary
  forms and links without JavaScript.
- Desktop layout checks cover 1280, 1440 and 1920 pixels, a long record title,
  long unbroken names, twelve phases, empty metadata and a search with no matches.
  The canvas and inspector remain side by side, with contained scrolling and no
  page overflow. Screenshots in `/tmp/graph-workspace-qa/` were visually reviewed.
- The existing mechanical plot browser suite passed its 28 curve cases, hover,
  PNG and CSV export checks at the same desktop widths.

The optional Chart.js cache serves the existing detail plots during browser
checks. The new Graph page does not add a JavaScript library or database
migration. The baseline local environment still warns that `staticfiles/` has
not been collected; browser checks serve source assets through Django's test
server.
