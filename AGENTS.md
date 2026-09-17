# AGENTS.md

## Start here when resuming

- Read the relevant sections of `README.md` for setup and current functionality
- Check `git status --short` and recent commits before changing files
- Do not assume another computer or Codex session has the previous chat, local environment, or credentials

## Project overview

This is a Django-based FAIR materials simulation data platform.

Core workflow:

- Upload JSON files
- Unwrap uploaded JSON files into individual data objects
- Store each data object with metadata
- Search and filter accessible data objects
- Display user-friendly data detail pages
- Export individual or selected accessible data objects as JSON

Current priority:

- Make the base platform stable, clear, and usable
- Focus on upload, validation, unwrap, search, detail display, and access control
- Treat knowledge graph, ontology, LLM assistant, and AI agent features as future enhancements

## Tech stack

- Python
- Django
- Django templates
- Bootstrap-based UI
- JSONField for raw JSON data

## Data model rules

- One uploaded JSON file may contain one or multiple data objects
- Each uploaded data object should become one `JSONData` record
- Each `JSONData` record stores:
  - `owner`
  - `data`
  - `access_type`
  - `shared_users`
  - `size_bytes`
  - `uploaded_at`

## Validation rules

- Validate required top-level fields only unless deeper schema validation is explicitly requested
- Extra fields are allowed
- Missing required fields must produce clear user-facing error messages
- Empty required fields must produce clear user-facing error messages
- Only valid data objects should be saved
- Current required top-level fields include `phase`, not `material`, unless code is explicitly changed
- `identifier` is not a required upload field: missing, null, or blank values receive an 8 character lowercase base36 identifier derived from the 24 required fields; collisions with different content extend it one character at a time
- Preserve valid supplied text identifiers; reject malformed values and surrounding whitespace with actionable errors
- Check generated and supplied identifiers against all stored records and the whole upload batch; retain the transactional recheck and never overwrite duplicates
- Store the full SHA-256 fingerprint internally for generated identifiers; use it to recognize repeated required content even after extension, and also check legacy 64 character identifiers
- Allocate and recheck generated identifiers under the final upload transaction lock, then account for their final JSON byte size; optional metadata is excluded from the fingerprint and existing identifiers are never recalculated automatically

## Access control rules

- The owner can always view their own data
- Public data can be viewed by other signed-in platform users; it is not anonymous access
- Shared data can be viewed only by explicitly shared users
- Only the owner can delete a data object
- Search results and detail-page access rules must stay consistent
- Never rely only on template-level hiding for security
- Always enforce permissions in Django views
- Live Data Objects is a separate public activity feed: show only `access_type="all"`, never owned or shared private data
- Do not apply the public feed restriction to ordinary search, My Data, or detail pages

## UI and UX rules

- Keep the UI compact, clean, and readable
- Search pages are for searching and browsing
- My Data pages are for managing the user's own uploaded data
- Detail pages may include management actions for the owner
- Search result pages should not include delete actions unless explicitly requested
- Preserve the existing visual style unless a change is requested
- Avoid large redesigns unless explicitly requested
- Keep Live Data Objects compact, with natural row heights and a bounded scrolling list; do not stretch rows to fill the screen

## Search rules

- Keep search practical and understandable
- Basic search requires all entered words, in any order, ignoring case; do not return records matching only some query words
- Keep the two advanced groups distinct: Common filters for general metadata and Data field filters for preset simulation parameters
- Common filters currently contains Title, Creator, Software, Phase, Identifier, Uploaded by, and Access; keep the `owner` query parameter for Uploaded by and do not add fields without a request
- Top and advanced-panel Search buttons submit the same combined GET form; both Clear links reset all conditions, and a keyword is optional
- Data field filters uses 11 preset simulation fields with explicit paths to the actual JSON schema in `apps/pages/advanced_search.py`; do not populate it from arbitrary uploaded JSON keys or duplicate common metadata such as owner or software version
- Test every offered field against `example_json_files`; friendly labels must map to real paths, including array entries, not merely similar sounding keys
- Keep old Ronak tokens working in bookmarked URLs with their original named key semantics, but do not offer them as new presets
- Match choices follow the field type and must also be validated on the server
- All active conditions must match the same accessible record; invalid conditions show errors and must not broaden the search
- Preserve existing bookmarked JSON paths with their exact-path semantics
- Keep search-page access and detail-page access aligned

## Code style rules

- Write all comments in English
- Write all docstrings in English
- The first line of every docstring must not end with a period
- Use clear, minimal, maintainable code
- Prefer small focused edits over large refactors
- Do not rename fields, models, routes, templates, or CSS classes unless necessary
- Do not introduce new dependencies unless necessary

## Working rules for agents

Before changing code:

1. Read the relevant files first
2. Understand the existing structure
3. Make the smallest correct change
4. Preserve current behavior unless the task explicitly asks to change it

When changing code:

- Keep changes local and minimal
- Do not rewrite unrelated files
- Do not remove existing working functionality
- Keep permission logic explicit and safe
- Keep user-facing messages clear and direct

When explaining changes:

- Mention exact file paths
- Give concrete implementation guidance
- Avoid broad abstract recommendations when direct code changes are possible

## Collaboration

- Explain work to the user in concise Chinese; keep application UI text in English
- The user prefers direct implementation of clearly requested changes, without approval at every routine step; still ask about material ambiguity or destructive actions
- After requested changes are complete and verified, the user wants `git add .`, a meaningful commit, and `git push`; inspect the diff first and do not include secrets or unrelated changes
- Never force push or discard another computer's uncommitted work to resolve a sync problem
- A successful push is not proof that Render has finished deployment; distinguish those states when reporting

## Local development and verification

- Follow README Local Setup and use this computer's project interpreter, not an absolute path copied from another machine
- With the PyCharm environment tool available, resolve the configured interpreter before running Python commands
- Use `DEBUG=True` and the local SQLite database for development and tests, never production database credentials
- Do not commit `.env`, credentials, local databases, uploaded private data, or virtual environments
- Run relevant Django tests for backend changes; run `node --test tests/js/*.test.cjs` for search or login JavaScript changes
- Browser tests require Chromium (set `CHROMIUM_BIN` if needed) and a Node runtime with global `WebSocket`; skipped browser tests do not count as verified
- Test layout changes at desktop and mobile widths, including long content and empty lists
