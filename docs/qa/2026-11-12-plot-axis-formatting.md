# Detail plot typography and shared scientific notation

The detail page and its PNG export now use one shared scientific multiplier
per axis, with independently selected powers for X and Y. Data arrays, paired
extrema, units, hover precision and CSV values are unchanged. The webpage still
shows the complete curve, without an initial-region inset or zoom control.

## Display rules

- Ticks use 20px text; axis descriptions and units use 21px; subscripts and
  scientific exponents use 16px. Sigma and epsilon retain matched visible
  glyph heights. Black axes, endpoint extensions and two origin labels remain.
- Regular tick steps expressible with at most two decimal places use ordinary
  decimals. A step such as 0.025 or 0.005 activates scientific scaling, as does
  a range magnitude of at least 10000. Extra digits of an irregular endpoint
  alone do not activate it.
- The common exponent is the base-ten order of the largest absolute bound.
  For example, the initial component-33 range uses `×10⁻⁴` once, with coefficients
  such as `−1.20`, `−1.00` and `−0.80`. The full example retains ordinary decimals.
- Displayed nonzero coefficients retain two-place half-up rounding. Extremely
  small endpoint coefficients keep their own scientific representation when
  necessary to avoid a false zero; its exponent is relative to the shared
  factor. Symbolic exponent subtraction also prevents numerical underflow.
- Multipliers participate in measured text layout, collision checks, title
  clearance and PNG padding. Titles stay 16 CSS pixels beyond the outer text,
  axis and arrow envelope. Arrow bases remain 24 pixels beyond positive bounds;
  negative axis ends retain their 24-pixel extension.
- PNG remains the only image export format, at 2304 × 1584 pixels with equal
  margins. No figure caption was added. At a placed width of 85 mm, a nominal
  16px script is approximately 5.02pt; at 89 mm it is 5.26pt. Further reduction
  changes the effective size.

## Publication references

The [Nature figure guide](https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/)
specifies 89 mm single-column figures and 5–7pt lettering at final size. It was
used as a typography reference, not a claim that this PNG satisfies every
journal's format requirements. The two-decimal switching threshold is a local
display choice, not a universal publication rule.

Separate origin labels are present in actual stress–strain figures:

- Behravesh, Lambert and Jahed, *Metals* 14 (2024), 221,
  [Figure 3](https://www.mdpi.com/2075-4701/14/2/221): crossing zero axes and
  positive/negative ranges, with a separate zero on each axis.
- Khayatzadeh et al., *Key Engineering Materials* 716 (2016), 891–896,
  [Figure 2](https://strathprints.strath.ac.uk/58115/1/Khayatzadeh_etal_KEM_2016_effect_of_plastic_deformation_on_elastic_and_plastic_recovery.pdf):
  separate horizontal and vertical zero labels.
- Mohd Zahri et al., *Frontiers in Materials* 8 (2021), 665219,
  [Figure 3](https://www.frontiersin.org/journals/materials/articles/10.3389/fmats.2021.665219/full):
  separate zeros in both the main compression curve and its inset.

These examples support retaining two zeros. They do not establish that a single
unambiguous origin label is prohibited.

## Verification

The mechanical plot unit tests cover independent multipliers, the two-decimal
boundary, half-up ties, unchanged bounds and tiny signed endpoint coefficients,
including a coefficient outside JavaScript's representable floating-point range.
The complete JavaScript suite passed 148 tests with no skips.

Desktop browser checks cover measured text bounds, title and arrow clearance,
origin zeros, full curve data, hover, CSV and PNG. The first 25 original
component-33 samples are an offline fixture, checked against the local example
when available; this does not introduce a website zoom feature.

The browser suite passed 31 synthetic cases at 1280, 1440 and 1920 pixels wide,
plus the original local example, the first-25-sample fixture, PNG downloads and
empty-state checks. It also measured every drawn font at an 85 mm placement
width. Fifteen Django plot-schema and mechanical-CSV tests passed separately.
No browser tests were skipped. A Canvas font-string serialization difference
(`22.909090909…px` versus `22.9091px`) required a 0.0001px comparison tolerance;
actual glyph edges matched, and the 0.15px geometry tolerance was unchanged.

Screenshots and PNGs in `/tmp/plot-shared-exponent-browser` were inspected for
the real full curve, first 25 samples, mixed-sign axes and independent X/Y
exponents. The full and initial example PNGs retain 250 and 25 original paired
samples respectively, with no added origin sample or fitted line.
