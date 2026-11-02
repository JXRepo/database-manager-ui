# Charts readability and software grouping — 2026-11-02

The dashboard repeated coverage totals and explanations on each card, truncated
phase, texture and software names, and counted Abaqus CAE spellings separately.

Changes:

- `templates/charts/index.html` removes repeated per-card totals and explanatory
  footers. Card-heading hover and keyboard focus retain the inclusion rules,
  coverage denominators and distinction between phase and object counts.
  `static/assets/js/charts.js` enhances the native heading titles with immediate
  tooltips; clicking a heading does not navigate.
- `apps/charts/plots.py`, the category, bubble and column templates, and
  `static/assets/css/charts.css` render full names with wrapping. Very long text
  scrolls within a bounded plot area. Model names keep their family in the color
  legend and hover details instead of repeating it in each visible label.
- Phase marks show counts, with percentages in hover details. Parenthetical
  qualifiers in supplied phase names remain intact. The loading heatmap places
  Mode below its columns and omits the separate color scale. Grain summaries
  retain Median and Min–max, with box definitions in the heading tooltip.
- `apps/charts/analytics.py` groups explicit Abaqus and Abaqus CAE spellings,
  ignoring case and separators, as Abaqus. Aliases within one object count once.
  `apps/charts/views.py` applies the same grouping to saved software filters.
  Other software names stay distinct; source JSON, exports and object-list
  descriptions retain the supplied names.

Verification:

- The new software regression failed before implementation and passed afterward.
  It covers bare, slash, spaced and uppercase spellings, duplicate aliases within
  one object, private/shared exclusions, old bookmarks and unchanged source data.
- All 61 Charts tests passed with Chromium, with no skips. Browser checks cover
  1280, 1440 and 1920 pixel desktop widths, full text bounds, long unbroken and
  Chinese labels, expanded categories, empty scopes, heading tooltips, keyboard
  operation, disabled JavaScript, exact intervals and legacy object-list links.
- Dashboard, long-label, normal software and sample-object screenshots were
  visually inspected. Django system checks and `git diff --check` passed.
- An intermediate run hit the existing concurrent in-memory SQLite `KeyError`
  in background page requests. The final unchanged run passed all 61 tests in
  31.348 seconds; no production database was used.

Command:

```sh
DEBUG=True CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.charts --noinput
```
