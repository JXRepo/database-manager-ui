# Detail feedback verification

Implemented the agreed feedback from the November 10 meeting.

## Tensor presentation

Stress and strain use sigma and epsilon with lowercase mathematical subscripts
in the matrix, face hover and native fallback. Select all, Clear and component
multiselect remain available; repeated action group buttons and cell captions
are removed.

Supplied equal reciprocal entries share an upper triangle control. Both internal
keys remain selected and both face pairs respond to hover/focus. Missing, invalid
or unequal counterparts remain separately visible. Original JSON and magnitude
details are preserved, including without JavaScript.

## Mechanical curves

Axes and numbers are black, ticks use 16px text, and sigma/epsilon use the same
italic serif font. Range endpoints are always labelled. Pixel spacing keeps
ordinary ticks clear of long endpoint labels; near-zero bounds retain their
signs, with the two origin labels separate.

PNG export redraws an independent chart at three pixels per CSS pixel, with equal
white margins. At the usual 720 × 480 display size the image is 2304 × 1584 pixels.
The export omits the active hover marker and tooltip and keeps the live chart's
size and interaction unchanged.

## Supplied example investigation

`example_json_files/a46fde6c.json` has 18 supplied mechanical arrays. All values
match through the metadata compatibility view, plot extraction and CSV export.
The first total strain 33 value is approximately -5.47e-6, while the first plastic
strain 33 value is approximately -3.98e-38. The first 25 total strain samples span
about 0.1025% of the full X range, less than one pixel at full-scale display.
The early segment is preserved and appears beside the vertical axis.

The source has 242 stress 23 samples and 250 samples in each of the other arrays.
Calculated equivalent stress and its paired plot therefore contain 242 samples;
CSV retains 250 rows and leaves the shorter column's final cells blank. No values
were synthesized and no data mapping fix was needed.

## Verification

- `node --test tests/js/*.test.cjs`: 139 passed, zero skipped.
- With `DEBUG=True`, the configured local `.venv/bin/python` ran
  `apps.pages.test_plot_schema`, `apps.pages.test_mechanical_csv`,
  `apps.dyn_api.test_metadata_compat`, `apps.pages.test_bc_schema`,
  `apps.pages.test_boundary_browser` and `apps.pages.test_plot_browser`:
  46 passed, zero skipped.
- Chromium covered 21 curve cases at 1280, 1440 and 1920 pixels, the supplied
  example, empty states, raw values, linked selectors, precise hover, PNG and CSV.
  PNG checks also used a display pixel ratio of two with an active hover marker.
- Tensor browser coverage included playback, symmetric and unequal reciprocal
  entries, signed faces, multiple records, retained selections and no JavaScript.
- Desktop screenshots and the exported PNG were visually inspected. Browser
  errors: zero. `git diff --check` passed.

An independent review found a reproducible long-endpoint collision. Two added
browser cases failed before pixel spacing was applied and passed afterward.
The boundary animation test also now samples actual animation displacement in
the same frame instead of assuming that 500ms of wall time means a visible tug.
This resolved an intermittent failure under concurrent browser workloads.

The other computer's changes through `b6971f3` were retained before the final
checks, including the updated compression example. These results describe local
verification; a successful push does not establish Render deployment completion.
