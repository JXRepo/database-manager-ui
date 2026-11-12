# Materials study workbench implementation plan

> **For agentic workers:** Use independent backend, UI and browser tasks with root-owned navigation integration; review the completed change before release.

**Goal:** Turn collection graphs into a focused materials-record exploration and comparison workflow.

**Architecture:** A versioned scalar projection feeds a bounded comparison matrix; ordinary GET parameters carry up to four pins and their reference order. Existing collection permissions and graph/manual-relationship functions remain authoritative.

**Tech Stack:** Django, templates, existing SVG renderer, plain JavaScript/CSS; no new dependencies or models.

**Spec:** `docs/superpowers/specs/2026-11-12-study-workbench-design.md`

## Global constraints

- Preserve raw JSON, original exports, current access checks and scientific meaning.
- At most four pins; comparison rows distinguish incomplete/ambiguous/truncated data.
- Keep phase/load contexts and explicit units; no inferred comparability or dependencies.
- Warm requests read summaries only; bounded preparation retains current safeguards.
- English UI, concise Chinese reporting, desktop layout with native GET fallback.

## Review focus

- A revoked or malformed selected ID must not silently shrink the comparison.
- PostgreSQL JSON missing-version semantics must not omit stale summaries from preparation.
- Long/truncated fields and reordered phases must not appear falsely equal.
- Pin/filter/page/reference state must survive navigation and remain user-bound.
- CSV and rendered values must not execute uploaded text or alter original data.

## Tasks

- [x] Backend: implement `study_comparison.py`, versioned projection and selected-only preparation; update deployment backfill; add permission-checked CSV views/routes and meaningful tests.
- [x] Integration: implement workspace/pin/browser context, complete-selection validation, graph focus, signed return fields and native GET links in root-owned modules; test stale selections and navigation.
- [x] UI: reshape collection workspace around Explore/Compare, a bounded searchable browser, pinned selection and domain-grouped matrix; preserve all existing editing/management/export flows.
- [x] Browser: verify actual pins across pages/search, reference changes, incomplete filtering, CSV, native navigation and desktop layouts; inspect screenshots and run existing graph workflows.
- [x] Review: inspect performance/permission/semantic boundaries, fix demonstrated issues, run required checks and update README/AGENTS/QA evidence.

Release procedure: inspect the complete diff, commit and push verified changes;
report public deployment checks separately from authenticated hosted acceptance.
