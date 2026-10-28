# Show tensor actions on the main cube

The user corrected the placement: Pull, Push and Slide must appear on the large
left cube itself. Remove the three right-side example cubes; keep compact action
controls and the complete numeric matrix on the right.

- Draw one conceptual colored, gridded cube in the existing Three.js scene, with
  a dashed original cube at the same center. Pull extends, Push shortens and Slide
  offsets opposite faces using the actual component direction and sign. Reuse
  the magnitude-independent point mapping; label the result as a conceptual
  action, not simulation output. Camera rotation and XYZ remain coherent.
- Show one explicit component at a time. Initially select the first supplied
  nonzero component. An action button selects its first matching component; all
  matching values remain available in the matrix. Show all returns to the face
  overview. Preserve missing selections when records change, exact steps, values,
  units and every independent component. No combined stress-derived deformation.
- Move Replay/Stop to the left cube. Animate the conceptual group once, keeping
  the dashed reference and local/scalar geometry fixed. Reduced motion still
  allows explicit manual replay; the final shape remains readable at rest.
- Preserve the separate optional data-derived small-strain preview and ordinary
  scalar/local displays. In mixed views local markers stay on the dashed reference.
- Verify real WebGL geometry, signed shear and initial/action selection, replay,
  shared-face hover, shape separation, empty states and 1280/1440/1920 layouts.
  Run Node and local SQLite Django/Chromium tests; inspect actual screenshots.
- Obtain one fresh read-only final review, commit and push per standing user
  instructions, then verify deployed assets and health before reporting completion.

Review focus: no example graphics on the right; the left main cube must actually
change; reference geometry, scalar/local markers and stored data must stay fixed;
never combine independent stress components into an implied simulated shape;
preserve hover/selection, finite playback and reduced-motion manual replay.
