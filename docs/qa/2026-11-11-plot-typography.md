# Mechanical plot typography verification

This follow-up addresses two-place tick numbers, consistent title spacing,
clearance around maximum ticks and the matching PNG output.

## Implemented behavior

- Nonzero tick labels have two decimal places with half-up rounding, including
  ties such as 1.005 to 1.01 and -2.675 to -2.68. Small or large scales use
  scientific notation with a two-place mantissa and an integer exponent. The
  two origin labels remain `0`; a small nonzero value never becomes `0.00`.
- The supplied data, paired extrema, true origin, sample order, precise hover
  values, raw-value panels and CSV precision are unchanged. Endpoint labels
  use the same rounding rule, while their positions retain the actual extrema.
- Tick text is 16px and black. Axis titles use 18px text and 13px subscripts;
  italic sigma and epsilon have matched visible glyph heights.
- Canvas glyph bounds determine tick placement and outer padding. Required
  endpoints are retained; colliding regular ticks are omitted. Near-zero
  endpoint labels can move outward without moving their ticks or the curve.
- Titles sit 16 CSS pixels beyond the combined envelope of the plotting area,
  ticks and arrowheads. When an axis passes through the interior of a signed
  plot, its title remains outside the plotting area. The gap therefore refers
  to the complete visible envelope, not a fixed distance from an interior axis.
- Positive arrowhead bases sit 24 CSS pixels beyond the range endpoint, with
  an additional 8px tip. Text avoids both arrowheads and other labels.
- PNG uses the same layout in an independent Chart instance and draws at three
  pixels per CSS pixel, with an additional 24 CSS pixels of white margin on
  every side. At 720 × 480 display size, the export is 2304 × 1584 pixels.
  Active hover markers and tooltips are omitted.

## Verification

- `node --test tests/js/*.test.cjs`: 144 passed, zero skipped. The 19 mechanical
  plot tests were also rerun after the final layout correction and passed.
- With `DEBUG=True`, the local `.venv/bin/python` ran
  `apps.pages.test_plot_schema`, `apps.pages.test_mechanical_csv` and
  `apps.dyn_api.test_metadata_compat`: 32 passed.
- `apps.pages.test_plot_browser`: passed in Chromium, using Node with global
  WebSocket and a cached Chart.js bundle through `CHARTJS_TEST_BUNDLE`.
  All 28 synthetic arrangements were checked at desktop widths 1280, 1440 and
  1920, including signed quadrants, cycles, half-up ties, long decimal bounds,
  small scientific values, near-zero reversals and symmetric signed ranges.
- Browser checks compare actual `fillText` bounds against the layout, check all
  text groups for overlap and cropping, measure title gaps and actual filled
  arrow vertices, and retain range, point-order, hover, raw-data and CSV checks.
- PNG checks verify dimensions, real threefold text drawing transforms,
  uncropped glyph bounds and absence of an active hover marker, including
  export from a display with device pixel ratio two.
- The supplied `a46fde6c.json` was checked on components 33, 22, 13 and 23.
  Desktop screenshots and the actual downloaded PNG were visually reviewed.
  Independent review found no outstanding issue after corrections.

Browser verification caught a near-zero endpoint label overlapping an arrow.
Arrow bounds now participate in collision avoidance. Independent review also
identified a potential title collision with the other axis's endpoint; both
axes' labels and arrowheads now contribute to the title envelope.

## Visual references

The review used actual stress–strain figures, including
[Tang et al., Figure 2](https://www.nature.com/articles/s41467-024-48435-6/figures/2)
and [Wang et al., Figure 2](https://www.nature.com/articles/s41467-024-51204-0/figures/2),
for legible type, clear units and whitespace. The existing requested two-axis
presentation is preserved. The
[Nature figure guide](https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/)
also informs the emphasis on readability at final size. PNG pixel dimensions
do not establish compliance with every journal's format or print-size rules.

This record describes local verification; pushing the commit does not establish
that Render has finished deployment.
