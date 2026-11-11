# Initial sample view implementation plan

> **For agentic workers:** Use the existing implementation and verification workflow for these focused tasks.

**Goal:** Make the supplied initial response inspectable without changing scientific data.

**Architecture:** Add a client-side prefix view to the existing Chart.js plot.
Reuse its current geometry and PNG renderer; keep CSV requests unchanged.

**Tech Stack:** Django template, plain JavaScript, Chart.js, Chromium checks.

**Spec:** `docs/superpowers/specs/2026-11-11-initial-plot-view-design.md`

## Constraints and review focus

- Default full curve; initial count min(50, paired length), integer 1…paired length.
- Initial sample indices remain original indices because the prefix starts at 0.
- Invalid inputs must not silently change the chart or export a misleading PNG.
- A variable change resets the view; shorter arrays bound the paired count.
- Full CSV and original raw values must survive prefix display and PNG export.
- Preserve all axis-layout, no-fabricated-samples and desktop-only constraints.

## Implementation and checks

- [x] Reproduce missing controls with a failing browser assertion.
- [x] Add compact view buttons, count input, validation and explicit view status
  in `templates/pages/data_detail.html`.
- [x] Render a prefix only in initial mode, restore full view on variable changes,
  and include the sample interval in initial-view PNG filenames.
- [x] Extend `apps/pages/test_plot_browser.py` and
  `tests/browser/mechanical-plot.cjs` with independent long data, counts,
  original samples, hover, resets and PNG/CSV assertions.
- [x] Run mechanical JavaScript and relevant Django/Chromium checks; inspect
  initial-view screenshots and downloaded PNG, then request independent review.
- [x] Document the numerical investigation and usage in README/QA/AGENTS and
  prepare the verified diff for commit and push.

Finish by committing and pushing the reviewed changes; report push and deployment
as separate states.
