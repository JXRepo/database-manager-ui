# Expressive tensor action animation on the original cube

The user's latest correction explicitly asks for obvious, jelly-like tugging,
squeezing and sliding rather than whole-cube scaling. Preserve the original glass
cube, its edges and white corner markers. Use small gripping pads on affected
opposite faces, no hands or arrows. Pads pull the face locally, with a brief hold,
soft rebound and return. Push indents and bulges; shear slides opposite faces.

Default to Action animation, explicitly illustrative (direction/sign, not physical
amplitude, material response or time). Keep the previous numerical view as a
separate Calculated strain option so scientific quantities and the data-driven
preview remain available. Keep all combinations, independent asymmetric components,
units, hover, exact records, original data/exports, local/scalar geometry and XYZ.

Implementation:
1. Pure signed local displacement and nonnegative tug envelope, tested for local
   versus uniform deformation, opposite faces, push bulge, shear, combinations,
   bounded motion and exact return. No inferred components or magnitude encoding.
2. Tessellate the original surface/edge geometry for tensor views; update its own
   vertices and corner positions. Add face grip pads to a separate disposable group.
   Warped highlights follow that same displacement. Restore buffers when switching.
3. Explicit 2.4-second Action playback; retain 1.2-second numerical playback,
   pause/resume/replay/reset and reduced-motion manual controls. No autoplay.
4. Verify real rendered vertex displacement and visible pixels at ×1, no uniform
   model matrix scaling, opposing pads, finite bounce/return, arbitrary mixtures,
   preserved numeric view, local markers and three desktop widths. Inspect frames.
5. Review diff and relevant Node/Django/browser checks, commit/push and independently
   verify deployed assets and health. No production data changes.
