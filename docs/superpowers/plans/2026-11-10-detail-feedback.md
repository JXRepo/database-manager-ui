# Detail feedback implementation plan

**Goal:** Apply the agreed meeting feedback to tensor controls and mechanical plots.

**Approved design:** Use traditional lowercase tensor subscripts with sigma for stress
and epsilon for strain. Collapse only supplied, equal reciprocal entries into one
upper triangle control while retaining both internal selections and face responses.
Remove redundant action labels. Keep the original cube, playback and raw data.
Make curve axes and numbers dark and readable, label range endpoints, and export
a clear PNG with the same content. Investigate total strain against the supplied
`a46fde6c.json` rather than adding unrecorded elastic samples.

**Architecture:** Keep the current Django template, Chart.js plot and tensor modules.
No new application dependencies or data migrations. The shared template is edited
in separate tensor and plot sections. Python checks use the configured local venv
with `DEBUG=True` and SQLite.

## Tasks

- [x] Update tensor labels, controls, reciprocal selection and linked hover in
  `static/assets/js/mechanical-bc-*.js` and the tensor area of
  `templates/pages/data_detail.html`; retain an accessible native fallback.
  Check symmetric, asymmetric, missing, zero, strain and multiple-record cases.
- [x] Update the plot section of `templates/pages/data_detail.html`, with
  endpoint and collision checks in `tests/js/mechanical-plot.test.cjs` and desktop
  render/download checks in `tests/browser/mechanical-plot.cjs`.
  Preserve tiny signed bounds, two origin labels, sample order and curve hover.
- [x] Trace the supplied example through metadata compatibility, plot extraction
  and CSV. Add focused regression coverage for total/plastic separation and the
  early samples. Change data handling only if evidence establishes a defect.
- [x] Update README and AGENTS to reflect the approved interface. Run focused
  JavaScript and Django/browser suites, inspect desktop screenshots and PNG,
  review the complete diff, then commit and push the requested changes.

## Review focus

- Equal reciprocal entries must highlight both face pairs through one control.
- Missing or unequal counterparts must remain visible without fabricated values.
- Endpoint labels must remain distinct near zero, beside adjacent ticks and in PNG.
- Export resolution must not depend on the display's device pixel ratio or hover.
- Total and plastic strain arrays must remain separate and preserve recorded points.

## Evidence and decisions

- Initial working tree was clean at `98f27cb`.
- The user approved this design in conversation and then requested implementation;
  routine implementation choices do not require another approval.
- The supplied sample preserves all 18 original curve arrays through extraction and
  CSV. The initial total-strain segment occupies less than one pixel at full scale.
  No synthetic elastic segment will be added.
- Synced the other computer's six commits through `b6971f3` before final checks.
  Kept its compression example and CRLF handling while updating the boundary test
  for component controls.
- Independent review reproduced overlapping long endpoint labels; actual pixel
  spacing now prioritizes endpoints and omits adjacent regular ticks. The new
  browser cases failed before the fix and passed afterward.
- Final checks: 139 JavaScript tests and 46 focused Django tests passed without
  skips, including both desktop Chromium suites. See the verification report.
