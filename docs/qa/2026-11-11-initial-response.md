# Initial response diagnosis

The supplied example contains an initial near-linear stress–total-strain
response. The complete strain range compresses that part of the curve against
the vertical axis. This investigation found no need to reconstruct missing
elastic samples or change the uploaded numbers.

Source: [`example_json_files/a46fde6c.json`](../../example_json_files/a46fde6c.json).
The identifier is `a46fde6c`; the title is “Stress-Strain Analysis of
Polycrystalline Copper with Goss Texture Using Crystal Plasticity FEM”. Stress
is supplied in MPa and strain has unit `1`. Indices below are zero based.

## Numerical method and results

For each normal component, take the first 25 original samples, indices 0–24:
`x = total_strain.strain_ii[0:25]` and
`y = stress.stress_ii[0:25]`. Fit `y = a*x + b` by ordinary least squares with a
free intercept. No zero sample is inserted, and no sample is reordered,
interpolated, smoothed or discarded. The calculations use the stored floating
point values; displayed results below are rounded only for readability.

The following formulas reproduce the diagnostics, where the sums run over the
25 supplied samples and `mean` denotes the arithmetic mean:

```text
a = sum((x - mean(x)) * (y - mean(y))) / sum((x - mean(x))**2)
b = mean(y) - a * mean(x)
R² = 1 - sum((y - (a*x + b))**2) / sum((y - mean(y))**2)
maximum plastic ratio = max(abs(plastic_strain_ii[i] / strain_ii[i]))
```

The total strain denominators are nonzero for all samples in this diagnostic
window. The ratio is a comparison of supplied components, not an inferred
fraction of elastic or plastic work.

| Component | Slope a (MPa) | R² | Maximum absolute plastic/total ratio (%) |
| --- | ---: | ---: | ---: |
| 11 | −1151.226757 | 0.999999999806 | 0.00107214 |
| 22 | 11731.029898 | 0.999982915151 | 0.00008910 |
| 33 | 131033.742364 | 0.999999994413 | 0.00084151 |

For component 33, the fitted intercept is `−0.000947285097 MPa`. The strain
range is `−0.000136865612558` to `−0.000005473843910`; the stress range is
`−17.934112549` to `−0.717458725 MPa`. The initial path slope is therefore
approximately `131.034 GPa`, with a very small supplied plastic component.

The entire component 33 curve reaches strain `−0.133546447586274`. Measured
from the true origin, the first 25 samples occupy about `0.1025%` of that full
horizontal range, less than one pixel even across a 720-pixel canvas. For a
separate diagnostic comparison, the first 50 samples have a strain bound of
`−0.001019646479252`, so the same initial samples occupy approximately `13.42%`
of that restricted range. These are range ratios, not a measurement of the
final rendered plot width or a requirement for webpage magnification.

## Departure from the initial line

Keep the component 33 fit from indices 0–24 fixed. For each later sample, compute
`abs(actual_stress - fitted_stress) / abs(fitted_stress)`. The table reports the
first subsequent sample exceeding each chosen threshold:

| Relative deviation threshold | First index | Actual deviation (%) | Absolute plastic/total ratio (%) |
| --- | ---: | ---: | ---: |
| 0.1% | 31 | 0.120550 | 0.103599 |
| 0.5% | 34 | 0.595147 | 0.552923 |
| 1% | 36 | 1.577967 | 1.498258 |
| 5% | 39 | 5.878511 | 5.701461 |

These thresholds describe numerical departure from a selected reference line.
They are not yield criteria, detected elastic limits, or a recommendation to
discard later samples. Selecting 25 samples for this diagnosis also does not
establish a universal fitting window.

## Why the slope is not automatically Young's modulus

The file describes Goss-textured polycrystalline copper, anisotropic elasticity
and multiaxial loading. Its supplied stiffness constants are `C11 = 170000`,
`C12 = 124000` and `C44 = 75000`, all in MPa. At the first sample,
`sigma_11 / sigma_33 ≈ 0.00698034` and
`sigma_22 / sigma_33 ≈ 0.01015837`: the transverse stresses are not zero.

Young's modulus has the familiar axial slope interpretation under the relevant
uniaxial elastic test conditions. General anisotropic elasticity couples
stress and strain through stiffness or compliance tensors; preferred texture
can also make polycrystalline metals anisotropic. See A. F. Bower,
[Applied Mechanics of Solids, sections 3.2.6 and 3.2.8](https://solidmechanics.org/Text/Chapter3_2/Chapter3_2.php),
checked on 2026-11-11.

For this example, the numerical results are loading-path slopes. The negative
11-component slope and the different 22-component slope illustrate why a
component plot must not automatically label its fitted slope as E. The three
supplied stiffness constants alone do not directly establish the effective
Young's modulus of this polycrystal. The orientation based verification below
now uses the 343 supplied orientations to make an independent estimate and
quantifies the small transverse stress correction for component 33. This
diagnosis does not reconstruct elastic strain by assuming that the stored
total and plastic strain arrays can be subtracted in the finite-strain regime.

## Independent elasticity check

The initial 33 slope is consistent with the elastic constants and texture in
the source. With equal grain volumes and the default MTEX Bunge convention,
the Hill estimate predicts `131.14 GPa` along the recorded stress path,
compared with the measured initial slope of `131.03 GPa`: a difference of
`−0.08159%`. This is a quantitative consistency check, not an exact rerun of
the original CPFEM simulation or a measurement of the complete effective tensor.

### Source and assumptions

The publicly deposited
[Goss dataset, Zenodo 13885748](https://zenodo.org/records/13885748), contains
`c779c1a4.json` (204,021 bytes, MD5 `0e032c6aa4ebc3e5a5bdead1f598c338`).
Its complete stress, total strain and plastic strain arrays are identical to
the local `a46fde6c.json`. The orientations and constitutive parameters also
match exactly. Both use input path `../DataBase/Keys/592bb0abb1/inputs`.
The differing identifiers and top-level `material`/`phase` names do not change
these compared numerical inputs.

The [associated metadata paper, section 5 and figure 6](https://advanced.onlinelibrary.wiley.com/doi/10.1002/adem.202401876)
describes this Goss example as 343 grains with eight elements per grain,
structured discretization and periodic boundary conditions. For this check,
each supplied orientation receives weight `1/343`. The JSON has no explicit
per-grain volumes, so equal volumes remain a stated modeling assumption. The
initial orientations are used only for the small initial strain range.

The input constants are `C11 = 170`, `C12 = 124`, `C44 = 75 GPa`. Each grain's
cubic stiffness is rotated into specimen coordinates using its three Euler
angles in radians. The rotation maps crystal to specimen, following the
[MTEX convention](https://mtex-toolbox.github.io/MTEXvsBungeConvention.html).
The metadata names MTEX but does not explicitly specify a nondefault Euler
convention or an additional specimen-frame rotation; this check assumes neither.

### Calculation independent of the strain curve

Use an orthonormal Mandel basis ordered `11, 22, 33, 23, 13, 12`, with both
stress and strain shear entries multiplied by `sqrt(2)`. Compute the rotated
grain stiffness matrices `C_g`, then the
[Voigt, Reuss and Hill estimates](https://mtex-toolbox.github.io/TensorAverage.html):

```text
C_V = mean(C_g)
C_R = inverse(mean(inverse(C_g)))
C_H = (C_V + C_R) / 2
S = inverse(C)
E_3 = 1 / S[2, 2]
```

None of these estimates uses the recorded strain values. To account for the
actual loading path, regress each stress component against `sigma_33` over
indices 0–24, with a free intercept. The resulting slope ratios are
`r_11 = 0.00698205542`, `r_22 = 0.0101596070`, `r_33 = 1`; shear terms are
negligible but retained. For this proportional stress path, the initial
elastic prediction is `M_33 = 1 / (S @ r)[2]`. Recorded strains are used only
for the separate observed slope and subsequent comparison.

| Elasticity estimate | Uniaxial E₃ (GPa) | Predicted actual-path slope (GPa) |
| --- | ---: | ---: |
| Reuss | 127.87 | 128.45 |
| Voigt | 133.21 | 133.81 |
| Hill | 130.55 | 131.14 |
| Observed first 25 samples | Not independently measured | 131.03 |

Within the stated assumptions, Reuss and Voigt bound uniaxial `E_3`. The
actual-path column contains corresponding predictions, not an asserted
rigorous bound on a general multiaxial component slope. Hill is an estimate
inside the elastic energy bounds; it is not an exact homogenization solution.

For Hill, the transverse stresses increase the predicted slope from
`130.553361 GPa` to `131.140743 GPa`, about `0.44992%`. Thus multiaxial coupling
is small for this particular 33 response. It does not prevent a meaningful
comparison to directional Young's modulus. It still does not make every
component slope a Young's modulus.

Fits using the first 5, 10, 15, 20 and 25 samples give respectively
`131.063133`, `131.055892`, `131.048664`, `131.041414` and `131.033742 GPa`.
The conclusion is therefore stable across these initial windows, not specific
to selecting exactly 25 points. These are numerical sensitivity checks, not
independent experiments or uncertainty intervals.

### Reproduction and limits

Run the offline NumPy script from the repository root:

```bash
.venv/bin/python docs/qa/verify_initial_elasticity.py example_json_files/a46fde6c.json
```

Optionally add `--public-copy /path/to/c779c1a4.json` to compare a locally
downloaded copy of the public deposit. The script does not download or alter
any data. It checks the rotation against MTEX's documented 10°, 50°, 20°
example, proper rotation matrices, positive stiffness, isotropic rotation
invariance, the Voigt/Reuss ordering, and the cubic directional compliance
identity for all 343 orientations. These checks and the public-source
comparisons passed on 2026-11-11.

The result supports an initial response dominated by elasticity whose slope
agrees closely with a texture based elastic prediction. Together with the
tiny plastic component and the full-range compression calculated above, it
answers the missing-elastic-segment concern for component 33 without changing
the curve or the website. The exact effective `E_3` would require the full
original model and a uniaxial elastic calculation, or its independently
determined effective compliance tensor. A close Hill estimate does not
validate every component, later plastic response, or the entire simulation.

## Withdrawn webpage feature

Commit `279c0e9` introduced an optional `Initial samples` view with an editable
count, initially `min(50, paired sample count)`. It also added PNG filenames
identifying the displayed sample interval. The user subsequently chose not to
have magnification on the webpage, so this feature and its implementation plan
are withdrawn.

The current product decision is to show the complete paired curve only, without
an initial sample count or local zoom controls. Keep the original samples,
axis typography, precise hover values, complete PNG plot and full CSV columns.
Curve redraws remain free of animation. There is no automatic fit, E estimate,
yield point or elastic limit in the UI.

A magnified diagnostic figure, if shared with Ronak, would serve only to show
that the initial near-linear response exists in the supplied data and is
compressed by the full plot range. It does not establish Young's modulus and
does not represent a request for a webpage feature. The numerical investigation
above remains valid independently of the withdrawn view controls.

## Historical verification of the withdrawn feature

The following results were recorded for the implementation before its removal.
They describe that earlier state, not verification of the current removal.

- Mechanical plot JavaScript checks: 19 passed; complete JavaScript suite:
  144 passed, zero skipped.
- With `DEBUG=True`, `.venv/bin/python manage.py test` for
  `apps.pages.test_plot_schema`, `apps.pages.test_mechanical_csv` and
  `apps.dyn_api.test_metadata_compat`: 32 passed.
- `apps.pages.test_plot_browser` passed with Chromium and the cached Chart.js
  bundle. It retained 28 layout cases at 1280, 1440 and 1920 desktop widths.
  The added checks used an independent 250-point fixture and the supplied component 33.
  They verified original 50/25-point prefixes, actual axis ranges, index 11 hover,
  unchanged source/raw data, invalid counts, Enter, one-point views, full-view
  restoration and variable changes with different paired lengths.
- The actual exported PNG contained the selected 25 points and matching ranges,
  at 2304 × 1584 pixels. CSV was compared row by row against all 250 original
  samples, even while the plot displayed 25 points.
- Initial 50/25-point desktop screenshots and the actual 25-point PNG were
  visually inspected. An independent reviewer found no outstanding issue.

That browser check exposed a misleading intermediate curve during Chart.js's
default draw animation after a view change. The earlier implementation disabled
curve animation, and that behavior is retained in the current product decision.
The earlier final browser run passed with the original axis, typography, hover
and export checks retained.

## Removal verification

- `node --test tests/js/mechanical-plot.test.cjs`: 19 passed.
- With `DEBUG=True`, `.venv/bin/python manage.py test` for
  `apps.pages.test_plot_schema`, `apps.pages.test_mechanical_csv` and
  `apps.pages.test_plot_browser`: 16 passed.
- Chromium checks retained all 28 layout cases at desktop widths 1280, 1440
  and 1920, and asserted that the initial sample controls are absent.
- The supplied component 33 screenshot and the complete-curve PNG export were
  visually reviewed after removal.

These results cover the local removal. A successful push does not confirm that
Render has finished deployment.
