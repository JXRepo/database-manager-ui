# Study analysis Implementation Plan

> **For agentic workers:** Use independent tasks with file ownership, root integration and a fresh whole-change review. The user has authorized implementation and autonomous delivery.

**Goal:** Locate detailed differences quickly and save a complete private analysis for later continuation.

**Architecture:** Native filtered detail tables with progressive enhancement; a collection-owned saved-state model with revision checks and source fingerprints; existing signed navigation remains the common continuation mechanism.

**Tech Stack:** Django, templates, plain JavaScript/CSS, SQLite and PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-11-14-study-analysis-design.md`

## Global constraints

Use `.worktrees/study-analysis`, baseline `087545a`, and the existing project venv.
Keep original JSON, permission rules, detail plots and reference materials unchanged.
English product copy; NumPy docstrings and readable code. No new dependencies.
State 16 KiB; title 120; notes 5,000; 100 analyses per collection; 12 per page.

## Review focus

- Revoked/deleted/nonmember source: opening must fail as a complete selection without hidden metadata.
- Concurrent tabs: stale update/delete must preserve the winning revision and submitted text.
- Dynamic controls: saved state must capture the visible detail and curve settings, including native fallback.
- Changed source JSON: reopening warns without silently accepting a new baseline.
- Deep table filtering: stable focus, empty matches, visible groups and reference column at all desktop widths.

## Tasks

- [x] Backend: models/migration plus `study_analyses.py` services/views and focused tests. Validate complete state and locks, compare source digests, expose context and native routes to root.
- [x] Difference navigation: `study_detail_navigation.py`, detailed template/CSS/JS and focused tests. Expose `detail_parameters(params)` and `apply_detail_navigation(context, params, *, base_url, navigation_params)`; no raw rereads in the enhancement.
- [x] Presentation and browser workflow: new saved-analysis template/CSS/JS, fixtures and real Chromium workflow. Root supplies `study_analyses` context; coordinate exact contracts with backend.
- [x] Root integration: study/signed state, routes, workspace response/context hooks, curve presentation persistence and templates. Add cross-feature integration regressions.
- [x] Verification: focused red/green tests, fresh independent review, full application and PostgreSQL regression, JS and desktop browser checks. Fix observed issues and verify final code.
Release procedure: README/AGENTS/QA, inspect final diff, commit, integrate latest main without overwriting concurrent edits, push and check deployment.

Backend owns `models.py`, migration `0019_savedstudyanalysis.py`, new backend module/tests.
Difference task owns its new navigation module/tests and existing detail template/CSS.
Frontend task owns new analysis presentation files and browser tests. Root owns all
shared integration files, documentation and curve state. Agents do not commit.
