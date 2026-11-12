# Manual collection relationships implementation plan

> **For agentic workers:** Use subagent-driven-development for the independent backend, UI and browser tasks; root owns graph integration and final review.

**Goal:** Persist user-drawn, editable directed relationships in private research collections.

**Architecture:** CollectionRelationship stores annotations independently from uploaded JSON. Existing SVG graphs overlay accessible links; native forms remain the canonical mutation path, enhanced by pointer drawing and JSON responses.

**Tech Stack:** Django, existing templates, SVG, plain JavaScript, SQLite and PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-11-12-manual-collection-relationships-design.md`

## Global constraints

- Preserve original JSON, existing access checks and metadata-derived graph meaning.
- Limit labels to 120 characters, collection relationships to 1,000, list pages to 12.
- No new dependencies; English UI and code comments, concise Chinese reporting.
- Save only on explicit POST with CSRF; revisions prevent lost updates.

## Review focus

- Revoked endpoint access must hide the complete edge, including counts and exports.
- Two tabs updating one edge must not overwrite each other's changes.
- Cross-page links must have a working focus/edit path with both endpoints visible.
- Pointer cancellation, panning, keyboard operation and exports must coexist.
- Failed saves must retain input without displaying a connection as saved.

## Tasks

- [x] Backend: add model/migration, `collection_relationships.py`, save/delete/export routes and regression tests. Root supplies `_workspace_response(..., relationship_form=None)` for native errors. Verify targeted Django tests.
- [x] Graph integration: pass accessible relationships into `build_collection_context`, overlay visible endpoints and focus `edge=ID`; provide `manual_editor` context, preserve signed return parameters, and add graph tests.
- [x] UI: add compact native relationship form/list, pointer ports and edit actions in a separate script/style; preserve graph renderer and portable image exports. Reuse backend response `{ok, redirect_url}` and errors `{ok:false,error,errors}`.
- [x] Browser: add isolated live-server/CDP test for draw/save/edit/delete/reload, cross-page selection, native fallback, failure recovery and desktop layout. Capture screenshots.
- [x] Review: fix reproduced deletion/revocation races and dense-edge selection, run final SQLite/PostgreSQL/browser checks, and update README/AGENTS/QA evidence.

Release procedure: commit and push the verified changes; report the commit and
actual public deployment checks separately in the handoff. Test evidence is in
`docs/qa/2026-11-12-manual-collection-relationships.md`.
