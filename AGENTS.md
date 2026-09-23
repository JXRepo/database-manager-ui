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
- Group upload feedback by JSON file, then data object in original order, then issue category; list each affected field separately and give guidance specific to that category
- Identify an object by its title and valid supplied identifier when available, with its file position as a reference or fallback; escape all uploaded text in feedback
- Treat each uploaded JSON file as one save unit: any validation, identifier, or sharing error rejects the entire file, with no partial objects or notifications saved
- Check every file and every readable data object, collecting independent errors instead of stopping at the first issue; reject invalid files and continue processing the others
- Show a status to the right of each selected file, with a spinner only for the file the server is currently processing; show all file results and grouped errors below the form after completion
- Keep one multipart submission and all batch prechecks, stream real file results in order after each atomic save, and retain ordinary form submission as a fallback; never simulate progress or retry automatically after a connection failure
- Prevent duplicate submissions without disabling the file input; retain confirmed results after an interrupted response and mark unfinished files as unconfirmed
- Check request file count, total bytes, and total object count before any saves; treat file size and content errors as local to that file, and retain a separate atomic identifier and quota recheck for each file
- Upload allowances are 5 files, 100 MiB per file, 250 MiB combined, and 1,000 objects per submission; stored JSON quota is 5 GiB per user, with depth 100 and 20 submissions per hourly window unchanged
- Release parsed JSON after each file's batch precheck and process one file at a time; application allowances do not guarantee the current hosting plan's capacity
- Current required top-level fields include `phase`, not `material`, unless code is explicitly changed
- Use the current MiMeDat `phase_name` for phase names in labels, summaries, and search; retain legacy name fallbacks without renaming uploaded JSON or treating phase_id as a name
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
- Focus UI design and implementation on desktop use; only address mobile layout when the user explicitly requests it
- Search pages are for searching and browsing
- My Data pages are for managing the user's own uploaded data
- My Data uses Access, Software, Phase, and Creator dropdowns sourced only from the current user's uploads; Creator refers to JSON metadata, not the uploader
- My Data combines selected filters on the same object, matches complete names ignoring case and surrounding whitespace, and counts each object once per option under the other selected filters
- Keep My Data filters and Clear available for empty results, preserve selected values in GET URLs, and limit bulk selection to the displayed records
- Detail pages may include management actions for the owner
- Detail metadata shows required top-level fields in mandatory_fields order, omitting mechanical_BC, stress, and total_strain from the metadata list while retaining their visualizations
- Show other supplied fields directly after required fields at each level, without an Additional metadata group; nested required order follows the locally recorded schema and applicable sharing or thermal conditions
- Collapse actual nested objects and object lists, even with one child; never merge flat fields by shared prefixes such as creator_affiliation, creator_institute, and creator_group
- Preserve field names, values, array item order, and complete JSON downloads; keep legacy required top-level placeholders except the three visualized fields, and do not add missing optional or nested fields or introduce deeper upload validation
- Search result pages should not include delete actions unless explicitly requested
- Preserve the existing visual style unless a change is requested
- Avoid large redesigns unless explicitly requested
- Keep Live Data Objects compact, with natural row heights and a bounded scrolling list; do not stretch rows to fill the screen
- Live Data Objects omits per-row Public badges and shows the total of all public objects, even when only the latest 20 are displayed
- Search results show Public or Private without expanding the row, show the matching total, and place public objects before private ones; retain newest-first ordering within each group

## Search rules

- Keep search practical and understandable
- Basic search and Common filters require all entered whole words, in any order, ignoring case, using the same matcher as new text Data field filters; do not return substrings or records matching only some query words
- Keep the two advanced groups distinct: Common filters for general metadata and Data field filters for preset simulation parameters
- Common filters starts with Identifier, Access, and Owner (uploaded by), followed by Creator, Software, Phase, and Title; keep the `owner` query parameter for Owner and do not add fields without a request
- Top and advanced-panel Search buttons submit the same combined GET form; both Clear links reset all conditions while preserving the panel's expanded or collapsed state, and a keyword is optional
- Data field filters uses 12 preset simulation fields grouped by microstructure, discretization and boundaries, material models, and loading and temperature; do not populate it from arbitrary uploaded JSON keys or duplicate common metadata
- Presets recursively search dicts and arrays by normalized field name, ignoring case, whitespace, underscores, and hyphens; `grain_number` is an explicit count alias, not permission to guess arbitrary synonyms
- Keep loading type and mode within `mechanical_BC`, excluding `thermal_BC`; counts and text must match values of the appropriate type, not arbitrary parameter containers
- Test every offered field against the synthetic `apps/pages/fixtures/search_fields.json` and local `example_json_files` when available; allow extra nesting without changing explicit bookmarked path semantics
- RVE continuity uses the Is comparison with actual JSON booleans; do not treat zero, one, or strings as booleans
- Global temperature queries use kelvin and convert explicit K, Celsius, or Fahrenheit units from the nearest enclosing units metadata; missing or unknown units and temperatures below absolute zero do not match
- Keep retired elastic and plastic parameter selectors usable only in active saved searches, with their original exact paths and Contains words behavior
- Keep old Ronak tokens working in bookmarked URLs with their original named key semantics, but do not offer them as new presets
- Match choices follow the field type and must also be validated on the server
- New text preset conditions use all entered whole words, ignoring order and case, with Match hidden; retain active saved Contains words and Equals text comparisons and all legacy selector semantics
- Keep Grain number as the displayed label for the grain_count preset and use Greater than or equal to / Less than or equal to for inclusive numeric comparisons
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
- Test layout changes at desktop widths, including long content and empty lists; do not run dedicated mobile checks unless the user explicitly requests them
