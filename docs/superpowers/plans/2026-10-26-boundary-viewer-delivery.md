# Mechanical Boundary Viewer Implementation Plan

> **For agentic workers:** Use executing-plans to implement the tasks inline,
> then requesting-code-review for one independent final review.

**Goal:** Deliver a clear, verified boundary viewer for all supported locations
and supplied scalar/tensor loads without changing scientific data.

**Architecture:** Keep the existing Django preparation, Three.js viewer and
tensor panel. Add display quantity/unit metadata at the preparation boundary;
make focused renderer and panel changes and exercise the actual DOM and WebGL.

**Tech Stack:** Django templates, Python, native JavaScript, Three.js, Chromium.

**Spec:** `docs/superpowers/specs/2026-10-26-boundary-viewer-delivery.md`

## Global Constraints

- English UI; concise Chinese user communication; no new dependencies.
- DEBUG=True and isolated SQLite only; do not read .env or production credentials.
- Preserve uploaded names, values, permissions and exports.
- No made-up directions, units, steps, time interpolation or inferred reciprocals.
- Desktop verification at 1280, 1440 and 1920; browser checks must not skip.

## Review Focus

- Missing and malicious unit/step content must not become HTML or guessed units.
- Scalar zero/invalid inputs must not look like positive loading.
- Negative normal plus two shear components on one face must remain distinguishable.
- Record changes must preserve real order and explicit selection when absent later.
- Mixed local and both whole-cube quantity types must have truthful captions.

### Task 1: Quantity labels and load record presentation

**Files:** `apps/pages/views.py`, `templates/pages/data_detail.html`,
`static/assets/js/mechanical-bc-tensor-panel.js`,
`apps/pages/test_bc_schema.py`, `tests/js/mechanical-bc-panel.test.cjs`.

**Interfaces:** Preparation adds `quantity_label` and `unit` to each condition.
Existing axes, tensor loads and source indexes remain stable. The panel still
emits its current view object and supports table selection buttons.

- [x] Add regression coverage for uploaded/missing units and exact steps.
- [x] Run the cases and confirm the missing display behavior.
- [x] Add explicit quantity labels, simplify single/multiple record UI and help.
- [x] Verify the Django responses, original data and exports; run panel tests.

### Task 2: Direction rendering and actual desktop delivery checks

**Files:** `static/assets/js/mechanical-bc-viewer.js`,
`tests/js/mechanical-bc-viewer.test.cjs`, `README.md`, `AGENTS.md`, `HANDOFF.md`.

**Interfaces:** Consume prepared quantity metadata and the existing panel view.
Keep all scalar/tensor and local/whole scenes independent.

- [x] Add real-browser regressions for zero arrows, tensor arrow counts and
  separation, quantity hover, record switching and matrix isolation.
- [x] Observe failures, then implement one arrow per tensor face/component,
  stable separate shear lanes, truthful scalar arrows and quantity hover/captions.
- [x] Run Node and relevant Django suites; exercise real detail pages and exact
  export for the five examples, mixed cases, long content and empty states.
- [x] Inspect screenshots at all desktop widths and collect evidence in the handoff.
- [x] Run independent review and fix necessary findings.
- [ ] Inspect the final diff, commit, integrate into main without discarding work, and push.

## Verification result

121 relevant Django tests and 131 Node tests passed with no skips. The real
Chromium regression covers all five tracked examples, zero and empty conditions,
independent nine-component tensors, supplied record order, mixed quantities,
hover/clear, rotation/reset, three desktop widths and native details without
JavaScript. Exact JSON exports and fixture bytes are unchanged.

Independent final read-only review: ready to merge, no unresolved findings.
PyCharm build reports success with limited diagnostics; executable tests provide
the validation evidence. Render deployment must be reported separately from push.
