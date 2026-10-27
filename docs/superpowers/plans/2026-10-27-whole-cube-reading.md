# Whole cube load reading implementation

Spec: `docs/superpowers/specs/2026-10-27-whole-cube-reading.md`

Goal: make whole cube load categories and normal/shear actions readable directly
from the diagram and its linked matrix. Execute inline; one final independent
review. User has authorized implementation, commit and push.

## Global constraints

Keep the orientation guide, local marker geometry, all supplied components and
stored/exported JSON unchanged. Never interpret scalar force sign as compression
or strain direction guides as forces. No new dependencies. English UI and Chinese
progress. Use the configured project interpreter, DEBUG=True and test SQLite.

### Task 1: Shared component meaning and panel

Files: `static/assets/js/mechanical-bc-tensor.js`,
`static/assets/js/mechanical-bc-tensor-panel.js`, `tests/js/mechanical-bc-*.test.cjs`.

Interface: `tensorComponentMeaning(component, value, isStrain = false)` returns
`{effect, name, action, color}` for known finite nonzero components, otherwise null.
Effects: outward, inward, shear. Both renderer and panel consume this helper.

1. Add tests for stress/strain actions, raw sign, zero/invalid absence, record
   updates, accessible action labels and exact numeric titles. Run focused Node
   tests; expected: new tests fail while existing tests pass.
2. Implement the helper and linked panel meanings. Run focused Node tests;
   expected: all pass without mutating input or changing record navigation.

### Task 2: Diagram and desktop layout

Files: `static/assets/js/mechanical-bc-viewer.js`,
`templates/pages/data_detail.html`, `tests/browser/boundary.cjs`.

Interfaces: consume Task 1 meaning helper; retain two selectable meshes per arrow
and existing tensor view callbacks. Do not alter scalar/local arrow factories.

1. Add browser checks for semantic geometry, face highlighting and the right-side
   matrix. Run boundary tests; expected: new assertions fail on old renderer.
2. Implement broad tensor arrows near faces, semantic legend, linked face accents
   and scalar quantity explanation. Move the tensor panel to the right column.
3. Run boundary/schema Django tests and all Node tests; expected: none skipped,
   all pass. Review screenshots at desktop widths and correct visible problems.

### Task 3: Review and delivery

Files: `README.md`, `AGENTS.md`, `HANDOFF.md` where relevant.

1. Record final behavior and verification. Review full diff and ask one fresh
   reviewer to check physical conventions, regressions and completeness.
2. Fix material findings and rerun affected checks. Commit the reviewed changes,
   fast-forward main, push, and verify public deployed assets when available.
3. Report actual verification and deployment state; no JSON re-upload is needed.
