# Scientific factors opposite Y tick labels

The approved placement table now puts each Y multiplier across its axis from
the tick numbers. For the component 12 example, the ticks and title stay on the
right and the Y multiplier moves to the left of the bottom end. X factors remain
on the tick side. Internal axes use fixed X-below/Y-left tick and title sides,
with factors at X-right-below and Y-top-right, even for asymmetric signed ranges.

Axes within one CSS pixel of the top or right edge retain their edge layout.
This preserves the visible layout of component 12's subpixel positive reversals
without altering their extrema, samples or origin. Factors move only outward
for collision clearance; they no longer switch ends. The complete nine-case
placement table is recorded in README.md.

Validation on 2026-11-14:

- The new opposite-Y-side regression failed against the previous implementation.
  `node --test tests/js/mechanical-plot.test.cjs` now passes all 28 tests.
  Literal expected placements cover the four single quadrants, four adjacent
  half planes, asymmetric full planes and tiny positive reversals.
- `DEBUG=True PLOT_SCREENSHOT_DIR=local-research/2026-11-14-plot-factor-opposite .venv/bin/python manage.py test apps.pages.test_plot_browser --noinput`
  passed in real Chromium, with no skipped checks: 41 fixtures at 1280, 1440
  and 1920px desktop widths, plus the original sample components.
- Nine representative layouts now also download actual PNGs and check the
  rendered glyph bounds, opposite Y factor side, fixed ends, 8px clearance,
  equal export margins and 3x resolution. Existing hover, original values,
  paired curves, endpoint extension, CSV and empty-data checks remain passing.
- Visually inspected all four single-quadrant arrangements, all four half
  planes, the asymmetric full plane, and actual component 12. Inspected PNG
  examples include component 12, positive and negative single quadrants,
  left and lower half planes, and the asymmetric full plane. No factor/title
  overlap or clipping was observed in these checks.
- An independent code review found no actionable layout or correctness issue.
  `git diff --check` passed.

Screenshots, downloaded PNGs and the local preview index are kept under the
excluded `local-research/2026-11-14-plot-factor-opposite/` directory. This change
does not modify raw JSON, data bounds, sample order, precision or plot controls.
