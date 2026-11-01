# Constitutive model labels — 2026-11-01

The model chart used a single-line label with CSS ellipsis inside a fixed-height
SVG region. Ordinary model names were shortened even when the complete text was
available in the tooltip.

`apps/charts/plots.py` now reserves multiple lines and adjusts model row heights.
`apps/charts/views.py` enables wrapping for the model chart and its expanded
categories. `templates/charts/category.html` and `static/assets/css/charts.css`
display these complete names with their bars and counts centered beside them.
Rendering works without JavaScript. Other category charts retain their existing
label behavior; source names, counts, colors and tooltips are unchanged.

Verification:

- The browser regression checks actual text rectangles against each model label
  region, including expanded categories. It detects the original truncation.
- All 60 tests in `apps.charts` passed with Chromium and no skips.
- Browser checks cover 1280, 1440 and 1920 pixel desktop widths, ordinary names,
  long unbroken text, Chinese text, empty scopes, expanded models, keyboard use
  and rendering without JavaScript.
- Normal model and expanded long-model screenshots were visually inspected.
- Django system checks and `git diff --check` passed.

Command: `DEBUG=True CHROMIUM_BIN=/usr/bin/chromium .venv/bin/python manage.py test apps.charts`
