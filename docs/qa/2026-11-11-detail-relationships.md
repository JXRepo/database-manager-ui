# Detail relationships

## Behavior

The detail page has a compact Relationships disclosure above its existing
metadata list. Its graph stays within the current accessible record: creators,
software, phases, constitutive models and available mechanical results. Models
connect to their own phase entry, including when two phases share a name.
Node selection reveals complete labels and metadata. Large graphs and long
information panels have bounded scrolling.

The backend uses the existing metadata compatibility view and prepared plot
series. It does not read other records, write metadata, copy curve samples into
the graph or add a database migration or dependency. Series summaries retain
full lengths and units and identify calculated equivalents. Explicit absence
of plasticity remains a phase note rather than a model node.

SVG nodes link to server rendered information sections. JavaScript enhances
selection and connection highlighting; native links remain usable without it.
User supplied text is escaped in labels, tooltips and detail panels.

## Verification

Using the configured `.venv/bin/python`, `DEBUG=True`, isolated SQLite test
databases, Chromium and Node 24:

```bash
DEBUG=True .venv/bin/python manage.py test \
  apps.pages.test_detail_relationships apps.pages.test_detail_metadata \
  apps.pages.test_plot_schema apps.pages.test_mechanical_csv \
  apps.pages.test_bc_schema apps.dyn_api.test_metadata_compat \
  apps.dyn_api.test_descriptive_fields --noinput

DEBUG=True CHARTJS_TEST_BUNDLE=/tmp/ronak-chart.js .venv/bin/python manage.py test \
  apps.pages.test_relationship_browser apps.pages.test_plot_browser --noinput

node --test tests/js/mechanical-plot.test.cjs
git diff --check
```

`CHARTJS_TEST_BUNDLE` points to an existing cached copy of Chart.js for the
unchanged mechanical plots. It is optional; the browser tests otherwise fetch
the page's existing Chart.js CDN bundle.

- 75 backend tests: field compatibility, distinct phase parents, legacy names,
  escaped HTML, access permissions, unchanged exports, series lengths and
  existing detail, boundary and curve behavior.
- Two browser tests without skips. Relationship checks cover normal content,
  12 phases with long unbroken names, and empty metadata at 1280, 1440 and 1920
  pixels, plus mouse selection, keyboard activation and native links without
  JavaScript. The existing plot browser check covers 28 curve cases, hover,
  PNG and CSV exports at the same desktop widths.
- 19 mechanical plot JavaScript tests.
- Browser screenshots in `/tmp/detail-relationships-qa/` were visually reviewed.
  The initial long label test detected SVG text exceeding its node. Labels now
  use bounded HTML text inside SVG, with complete text in the information panel.

The baseline local environment warns that `staticfiles/` has not been collected.
The browser tests serve source static assets through Django's test server.
