# Whole cube load reading

The user needs to distinguish whole cube XYZ force/displacement conditions from
stress/strain components without first understanding a tensor matrix. Keep the
existing orientation guide and local point/edge/face geometry unchanged.

## Design

- Identify the quantity and unit beside the diagram. Scalar loads keep the slim
  purple axis arrows; their sign describes direction, not tension/compression.
- Tensor components use broad straight arrows. Curved arrows would suggest a
  moment or rotation, which these components do not specify.
- Normal positive stress points away from both opposing faces (Pull / tension);
  negative stress points toward them (Push / compression). Strain uses Extend
  and Shorten, explicitly as direction guides, never as forces or predicted shape.
- Shear arrows run parallel to their corresponding faces, with independent lanes.
  Color and short action labels reinforce geometry: blue outward, orange inward,
  teal shear. Preserve each supplied component, including unequal xy and yx.
- In tensor-only scenes place arrows next to the faces. Mixed scenes retain room
  for local markers. Selection and hover emphasize the matching opposing faces.
- Put the matrix in the right column beside the cube, above the existing tables.
  Label its axes as direction and face, add action words to nonzero cells, and keep
  click isolation, hover, keyboard focus, record selectors and original precision.
- A compact pictorial legend explains outward, inward and parallel arrows. Do not
  add repeated explanatory paragraphs to the main view.

## Invariants and acceptance

- One tensor arrow on each opposing face per supplied nonzero component; fixed
  lengths, no inferred components. Zero/missing/invalid values have no arrow or
  action claim. Tiny signed values retain their sign even if rounded to 0.00.
- Cube tint continues to identify the whole region, independently of magnitude.
- Preserve all data, units, exports, record order/steps and opt-in strain preview.
- Validate pure semantics, panel interaction, actual Three.js geometry, linked
  highlights and desktop layout at 1280, 1440 and 1920 pixels with real Chromium.
- Review screenshots of tensor, scalar and mixed conditions. Run all Node tests
  and the boundary/schema Django tests; inspect the diff, commit and push as
  already requested. Report deployment separately from push.
