# Data driven deformation on the original cube

Implement natively with one fresh read-only final review. The user explicitly
requested preserving the original glass cube, arbitrary action/component
combinations and deformation amplitudes derived from uploaded values.

## Design and interfaces

- Keep the original surfaces, edges and white corner spheres. Transform that
  existing group; remove the replacement gridded model and fixed action amplitudes.
- A set of selected components controls both the highlighted faces and deformation.
  Pull, Push and Shear are independent multi-select group buttons, with Select all
  and Clear. Matrix buttons toggle components. Reciprocal shear entries are selected
  together for symmetric deformation, while their distinct supplied values remain
  visible and conflicting pairs prevent calculation rather than being averaged.
- Initially select all supplied nonzero components and retain the undeformed cube.
  Play/Pause/Replay deformation is explicit and finite, independent of recorded
  steps or physical time. Reset returns the original shape and camera. Record or
  selection changes reset the shape rather than silently replaying a history.
- `deformation_context(metadata)` sends only dimensions, units and the single
  phase's explicitly named elastic model and E/nu parameters; no raw phase arrays.
- `tensorDeformation(magnitude, selected, type, units, context)` returns actual
  small-strain matrix, source/assumption text, axial extension values and an error.
  Require nine finite numeric components with matching reciprocal values, explicit
  strain units (dimensionless or percent), and compatible stress/stiffness units.
- Strain uses the selected supplied tensor components directly. Stress uses the
  explicit single-phase isotropic linear elastic model only: epsilon_ii =
  (sigma_ii - nu*(sigma_jj + sigma_kk))/E, epsilon_ij = (1+nu)*sigma_ij/E.
  Reject unknown models, invalid parameters/units, multiple phases and incomplete
  or asymmetric tensors. This is a homogeneous small elastic preview, not a spatial
  solver or nonlinear material response. Unsupported cases retain the original
  cube and all values, with an actionable explanation.
- Display scale starts at x1 and is explicitly editable. Apply one uniform factor
  to the calculated strain without normalizing by its peak. Keep actual strain and
  axial length changes separate from display scaling. Limit real strain to a 5%
  row-sum bound for the small-strain model and visual strain to 45% to avoid inversion.
- Use I + progress*scale*epsilon for the original cube and tensor surfaces. Keep
  the existing local/scalar marker geometry independent; mixed views identify the
  undeformed reference and do not claim to solve those local boundary conditions.

## Work

1. Add narrow backend context extraction and pure deformation math with tests that
   fail first: copper exact values, doubled loads double strain, mixed selections,
   percent/Pa-GPa conversion, Poisson effects, input preservation and invalid data.
2. Replace exclusive controls with multi-selection and numerical preview/status.
   Verify arbitrary group combinations, paired shear selection, record navigation,
   missing values, display scale validation and complete unchanged matrix values.
3. Restore original glass geometry and connect its matrix to the numerical result;
   move playback to explicit finite play/pause/reset with a frozen camera. Remove
   unused fixed-amplitude geometry and normalized preview paths.
4. Verify actual Chromium render at 1280/1440/1920, retained original meshes,
   transformed world geometry, combinations, real replay/pause/reset, fixed data
   and markers, unsupported states, no JavaScript, exports and access isolation.
5. Run Node tests and local DEBUG=True SQLite Django tests with the PyCharm
   interpreter. Inspect real screenshots and frames, update docs, obtain one final
   review, commit/push and independently verify deployed files plus health.

## Review focus

Preserve the original model; never substitute fixed-amplitude shapes. Check stress
versus strain units, numerical conditioning and model eligibility; never silently
infer material properties or average asymmetric shear. Check arbitrary selection
combinations, actual versus amplified values, stale animation after selection,
resource disposal, scalar/local isolation and invalid or private uploaded data.
