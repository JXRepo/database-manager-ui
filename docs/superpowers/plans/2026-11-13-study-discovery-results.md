# Study discovery and result curves implementation plan

> **For agentic workers:** Use independent backend and frontend tasks with root-owned integration, then independent review and verification.

**Goal:** Help researchers find records to compare and inspect recorded curves alongside settings.

**Architecture:** Native candidate criteria over bounded summary projections; a separately authorized, bounded curve endpoint feeds progressively enhanced small multiples and optional overlay. Signed workspace navigation carries all canonical controls.

**Tech stack:** Existing Django, templates, plain JavaScript/CSS and canvas; no new dependencies or models.

**Design:** `docs/superpowers/specs/2026-11-13-study-discovery-results-design.md`

## Tasks

- [x] Candidate backend: implement `study_candidates.py` criteria parsing, strict classification, evidence, bounded preparation and native comparison links; add focused tests.
- [x] Curve backend: implement `study_curves.py` endpoints, complete access checks, actual byte/sample budgets, preserved curve extraction and conservative unit gating; add focused tests.
- [x] Integration: share summary preparation budgets; carry canonical controls through `study_workspace.py`, `collection_navigation.py` and native POST returns; add routes and navigation tests.
- [x] UI: add candidate controls/results and a compact result-curve disclosure, linked record selection, empty/error recovery and native fallback; preserve current desktop density.
- [x] Verification: test canvas math and real Chromium workflows, existing regressions, PostgreSQL access/preparation behavior; inspect screenshots and request independent review.
- [x] Delivery preparation: update README/AGENTS/QA and review the complete diff.

Release follows the validated change: commit and push, then check public deployment
separately from authenticated hosted acceptance. See the QA report for verification
and the final delivery message for the commit and deployment result.
