# Mechanical boundary viewer delivery

The user has delegated the final design and implementation of the detail-page
boundary viewer. The deliverable covers points, edges, faces, scalar whole-cube
loads, whole-cube stress and strain, and supplied load records. Keep the existing
desktop visual style and data model.

## Design

- Use location to identify the affected region: point marker, highlighted edge,
  filled face, or the whole cube. Preserve existing local geometry and fixed T
  markers. Scalar whole-cube loads retain one arrow per loaded axis and sign.
- Arrow geometry indicates direction, not quantity or magnitude. Identify Force,
  Displacement, Stress and Strain by their names and uploaded units in the table,
  cube caption and hover. Never invent units. Missing units are explicit.
- Whole-cube tensors retain an always-visible matrix and all nonzero supplied
  components by default. Draw one arrow per component on each opposite face
  (eight arrows for the copper example). Use separate face-parallel lanes for
  shear components so they do not cross normal arrows or each other. Selection
  and highlighting retain the same arrow positions.
- Preserve independent reciprocal components, signs, zeros, missing values and
  original order. Scalar zero or invalid magnitudes do not acquire positive
  arrows. Repeated local arrows indicate the region, not multiplied force.
- Show one compact explanation beneath the diagram and details in a native
  expandable help section. Avoid repeated status sentences and special-purpose
  jargon in the primary reading flow.
- A single tensor record has no record navigation. Multiple records use one
  explicitly labeled selector in supplied order. Display a supplied `step`
  exactly in its record label/details; do not invent a step or interpret it as
  time. Scalar load entries continue to map to loaded XYZ axes and do not become
  a timeline. Remove the redundant tensor range slider.
- Keep optional strain shape illustration under advanced controls, with its
  complete symmetric tensor requirement and normalized small-strain explanation.
- Keep table values and complete exports available without JavaScript. Preserve
  access checks and do not mutate stored JSON or the example fixtures.

## Approaches considered

Keeping three arrows per tensor component preserves the current clutter.
Replacing tensor components by resultants loses the supplied component meaning.
The selected design removes only repeated tensor arrows, separates intersecting
directions, and makes names/units explicit. This is the implementation decision
under the user's request for a finished deliverable, not a scientific inference
from arrow count or a change to the uploaded boundary conditions.

## Acceptance

Use all five tracked examples and additional zero/missing, negative normal,
nine-component, unequal reciprocal, strain, mixed-local, multiple-condition,
multiple-record and absent-step cases. Verify real WebGL, hover, matrix selection,
rotation/reset, table expansion, exact exports, and desktop widths 1280/1440/1920.
Run relevant Django and Node tests with no skipped browser tests. Review, commit
and push after verification; report deployment separately from Git push.
