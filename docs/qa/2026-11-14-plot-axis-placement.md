# Detail plot axis placement

The component 12 example had its axes at the top and right while its titles
appeared below and left. The title placement tested exact data signs, whereas
tick placement used the rendered axis position. Tiny positive values therefore
sent titles to the wrong side. Fixed right/top multiplier anchors also crowded
both factors around the upper right origin.

Titles now share the tick side and retain their measured 10px gap outside the
local tick envelope and plot boundary. Shared factors use `·10ⁿ`, stay separate
from titles, and choose visible axis branches. Single quadrant factors use
right/top, left/top, left/bottom and right/bottom ends for quadrants I–IV.
Axes with both signs prefer positive ends when space permits. Candidate ends
and outward clearance are measured without changing data or moving titles.

Validation on 2026-11-14:

- New unit regressions failed before the fix on the multiplication symbol and
  title sides for tiny positive reversals. After the fix,
  `node --test tests/js/mechanical-plot.test.cjs` passed all 26 tests.
- `DEBUG=True PLOT_SCREENSHOT_DIR=local-research/2026-11-14-plot-layout .venv/bin/python manage.py test apps.pages.test_plot_browser --noinput`
  passed in real Chromium: 37 data arrangements at 1280, 1440 and 1920px
  desktop widths, with no skipped checks.
- Browser assertions checked actual drawn glyph bounds, factor clearance,
  both origin labels, title gaps, readable endpoint extensions, original data,
  hover, linked selectors, CSV and PNG exports. Actual component 12 and its
  PNG export are now included alongside the existing sample components.
- Visually inspected all four quadrant placements, all four half planes,
  a cyclic curve, tiny signed reversals, crowded dual factors, and actual
  component 12 and plastic component 13. The component 12 PNG has X title
  above, Y title right, X factor upper left and Y factor lower right.

Screenshots and downloaded PNGs remain in the excluded local directory above.
The original JSON, ranges and sample order are unchanged. Internal axes retain
titles outside the plotting area; the website still shows one complete curve.
