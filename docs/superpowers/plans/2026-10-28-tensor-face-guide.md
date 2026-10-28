# Tensor face and action guide

The user approved replacing second-class arrows with highlighted load faces and
small conceptual Pull / Push / Slide illustrations. Implement natively in this
session, then obtain one independent read-only review before merging.

## Design

- The main reference cube retains its geometry and XYZ guide. Highlight opposite
  faces for supplied nonzero components, preserving the direction-i / normal-j
  convention, independent xy/yx values, units, filters and exact records.
- Show three compact action illustrations above the complete numeric matrix.
  Each keeps a dashed original outline, colored conceptual shape and light grid.
  Pull lengthens, Push shortens and Slide offsets opposite faces. No tensor arrows.
- Make these illustrations the action filters, with Show all available. Display
  component counts, including an explicit empty state. Matrix selection/hover
  links the relevant faces and illustration; selected examples follow the actual
  component orientation and sign without using its magnitude as deformation.
- Label examples as conceptual, not simulation output. Keep the existing opt-in
  symmetric small-strain preview and its required assumptions separate.
- Animate only the active illustration once; its final conceptual shape remains
  visible at rest. Manual replay works with reduced motion, automatic playback
  stays suppressed under that preference. Preserve stop and offscreen handling.
- Scalar loads, local markers, stored/exported JSON, units and steps remain intact.

## Implementation

1. Add grouped face data and sign-only conceptual geometry to
   `mechanical-bc-tensor.js`. Tests verify exact opposite faces, independent
   components, filters, signed shear and no magnitude dependence or input mutation.
2. Add `mechanical-bc-illustrations.js` for the SVG action guide. Adapt
   `mechanical-bc-motion.js` to animate a supplied drawing callback, restoring the
   final example on stop; retain explicit/manual preference semantics.
3. Integrate the guide in `mechanical-bc-tensor-panel.js` and the existing detail
   template. Preserve complete values, selection, record navigation and shape
   eligibility. Replace arrow-specific UI copy with face/selection wording.
4. Replace tensor arrow meshes in `mechanical-bc-viewer.js` with grouped opposing
   face surfaces/outlines. Mixed faces use a neutral color; component selection
   uses its action color. Face hover reports every associated component rather
   than guessing one. Keep the main cube, local/scalar markers and camera stable.
5. Update real Chromium coverage: no tensor arrow geometry; correct highlighted
   faces and full matrix at 1280/1440/1920; linked pointer/keyboard interaction;
   signed static examples; animation affects SVG only and ends at the same final
   shape; reduced-motion manual replay; missing/zero/invalid and mixed records;
   existing scalar, point, edge, face, export and no-JavaScript checks.
6. Run `node --test tests/js/*.test.cjs` and the local SQLite Django boundary/schema
   tests with DEBUG=True and the PyCharm-resolved interpreter. Inspect screenshots
   and motion frames, update README/AGENTS/HANDOFF, review, commit and push. Verify
   deployed changed assets against local bytes and health separately from push.

## Review focus

- Opposing faces must retain every independent component on a shared face.
- A mixed face must not silently inherit the color/meaning of its first component.
- Generic examples and data-derived strain preview must remain distinguishable.
- Hover/focus clearing must restore selection and never leave stale highlighting.
- Manual replay must not enable later automatic motion under reduced motion.
