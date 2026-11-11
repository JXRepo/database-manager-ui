# Initial sample view

Ronak wants the initial near-linear stress–total-strain response to be visible.
The supplied `a46fde6c.json` contains it: component 33 samples 0–24 fit a line
with slope 131033.742364 MPa and R² 0.999999994413. Their total strain occupies
about 0.1025% of the complete X range. The file describes anisotropic, textured
copper under multiaxial loading, so this path slope is not automatically a
Young's modulus measurement.

## Approach

Keep the existing full curve as the default and add `Full curve` / `Initial
samples` controls. Initial samples displays the first min(50, paired length)
points, with an editable count. This gives a large readable view without a
second chart or smaller inset. A general arbitrary sample range is more control
than needed for this initial-response task. Automatic elastic-range detection
or fitting is not part of this change.

The implementation choice follows the user's standing preference for direct
implementation; default 50 is a display convenience, not a detected transition.

## Behavior

- The count is an integer from 1 through the paired X/Y length. Change or Enter
  applies it. Invalid input retains the previous view, shows a clear error and
  disables PNG until corrected or the full view is restored.
- The status identifies the visible count, full paired count and original
  zero-based sample indices. Original point order, numbers and signs remain.
- Each view includes the true origin in its axis ranges without inventing an
  origin sample. Existing typography, hover and axis layout are reused.
- Switching variables restores the full view and default count. Switching views
  for the same variables preserves the most recently accepted count.
- PNG exports the visible view at the existing resolution; initial-view names
  include the sample interval. CSV keeps all samples and raw panels keep their
  existing behavior. UI copy clarifies full-series CSV and current-view PNG.
- No automatic E, yield point, elastic-strain subtraction, smoothing, fitting,
  interpolation, backend changes or new dependency is introduced.

## Verification

Check initial views using a synthetic long curve and the user's component 33;
compare every plotted point to the original prefix, inspect ranges and hover,
exercise invalid counts and reset behavior, and compare PNG/CSV downloads.
Keep all existing quadrant, typography and desktop browser checks.
