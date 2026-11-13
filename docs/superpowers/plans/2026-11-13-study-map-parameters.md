# Study map and parameters Implementation Plan

> **For agentic workers:** Use independent implementation tasks with explicit file ownership, root integration, then independent whole-change review. Follow the accepted design and run meaningful regression tests.

**Goal:** Find useful cross-record comparisons on a parameter map and inspect their actual model and loading differences.

**Architecture:** Versioned scalar map projections feed native grid and member filtering. Explicit bounded parameter inspection reads authorized selected records; existing curves and comparison pins remain the common workflow.

**Tech Stack:** Django, templates, existing plain JavaScript/CSS, SQLite and PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-11-13-study-map-parameters-design.md`

## Global constraints

No raw JSON or permission changes, semantic phase alignment, unit conversion,
scientific equivalence claims, new dependencies or models. Preserve current detail
plots. Use the project interpreter, DEBUG=True and synthetic local test records.
Worktree `.worktrees/study-map`, baseline `6806943`; user delivery consent persists.

## Tasks

- [x] Detailed parameters: `study_details.py`, focused extraction/access tests; expose `build_parameter_context(request, ids, *, collection=None, selection_token='')`; enforce complete access and byte checks, precise bounded values and explicit uncertainty.
- [x] Map backend: `study_map.py`, map projection and focused tests; bump summary version and integrate collection cache projection; expose canonical controls and `build_map_context(objects, params, *, base_url, navigation_params, preparation_budget=None)`.
- [x] Presentation: new map/details templates and scoped CSS, progressive enhancement only where needed; own new browser workflow and fixtures. Confirm contracts with backend/root before integration.
- [x] Root integration: workspace panel/state, signed navigation, native member filtering and pin persistence, explicit detail inspection, collection entry links and integration regressions.
- [x] Review and verification: independent scrutiny of precision/units/aliases/access/budgets; full application, focused PostgreSQL, JavaScript and real desktop Chromium tests.
Release procedure: README, AGENTS and QA evidence accompany the implementation. Inspect the final diff, commit, integrate, push and check public deployment; report hosted checks separately from authenticated acceptance.

## Execution notes

Initial design decisions: keep the existing Graph sidebar placement; add Parameter
map as a collection view rather than another application page. Newly opened saved
collections can enter the map while explicit existing Explore/Compare links retain
their meaning. Named research views are deferred as agreed. Independent tasks must
not edit shared integration files or commit; root coordinates final integration.
