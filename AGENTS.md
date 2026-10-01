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

- Validate the 24 required top-level fields and applicable nested and conditional required rules from the bundled MiMeDat schema profile; do not claim full JSON Schema compliance or enforce unrelated optional constraints
- Extra fields are allowed
- Recognize schema field names within their own parent ignoring case and separator punctuation; accept finite numeric strings at known numeric paths and explicit all/c sharing shorthand
- Accept CPU_specifications, CPU_specification and processor_specification as explicit aliases for processor_specifications, preserving uploaded names
- Descriptive fields may match all their words within one key at the same schema parent, ignoring word order, case, separators, simple trailing-s plurals and camel case; exact schema names and more specific known fields take precedence, and a key equally matching different requirements stays unrecognized
- Limit keyword matching and multiple-description aggregation to title, creator, creator_affiliation, date, rights, rights_holder, software, software_version, system, system_version, processor_specifications, input_path, results_path, phase_name and texture_type where defined by the schema
- Accept multiple matching descriptions with different values when at least one has content; reject all-empty matches, preserve every original key and value in detail rows and JSON export, and combine descriptions only in internal search and summary views
- Units, permissions, identifiers, numeric values, structural fields, load components and curves retain existing name and conflict checks; descriptive matching must not determine their meaning or select a value
- Unwrap singleton lists only at known scalar or object locations, including individual array entries; preserve genuine arrays and unknown metadata, never choose among multiple values, and check required emptiness after unwrapping
- Wrapped identifiers and explicit sharing tokens use the same duplicate and access checks as bare values; retain existing wrappers when filling a blank identifier automatically
- Preserve original JSON keys and values in storage and JSON export; use the shared metadata compatibility view for validation, search, summaries and plots
- Do not infer synonyms, move nested values to other parents, search arbitrary text for permission tokens, or silently choose between conflicting functional aliases
- Maintain the internal identifier lookup digest for alternative field spellings; preserve identifier text and the final duplicate and quota checks
- Missing required fields must produce clear user-facing error messages
- Empty required fields must produce clear user-facing error messages
- Required fields include active conditional requirements; null, blank text, empty lists and empty objects are empty, but zero and false are not; optional blanks are preserved
- Resolve schema references only through the bundled trusted snapshots; never fetch a user's uploaded $schema URL
- Recognize records in lists, identifier dictionaries and nested collections using the same field name matching; stop at record boundaries and retain incomplete members for errors instead of dropping them or changing stored field names
- Group upload feedback by JSON file, then data object in original order, then issue category; list each affected field separately and give guidance specific to that category
- Lead errors across objects with a compact summary of identical fixes and their affected count or exact positions; keep missing and empty values distinct, use short actions such as Add and Fill in, and retain all object details in original order behind expandable sections
- Open a single failed object's corrections immediately, collapse repeated technical messages behind Show reason, omit a source location that repeats the identifier, and show the final upload summary only once
- Identify an object by its title and valid supplied identifier when available, with its file position as a reference or fallback; escape all uploaded text in feedback
- Treat each uploaded JSON file as one save unit: any validation, identifier, or sharing error rejects the entire file, with no partial objects or notifications saved
- Check every file and every readable data object, collecting independent errors instead of stopping at the first issue; reject invalid files and continue processing the others
- Show real Checking n / total and provisional Saving n / total counts in both background and NDJSON uploads; retain Checked n / total on final file rows, show Uploaded only after the entire file commits, and keep ordinary form submissions working
- Stream counts from the actual validation and save operations, never replay or delay them; close processing iterators on disconnect so an interrupted file and its notifications roll back while earlier file commits remain
- Use no spinner for object checking or saving counts; keep errors immediately below the form, with expandable details for multiple failed objects
- Keep the upload picker compact and allow it to grow with selected files; show checking counts beside each file only, retain progress on other pages and operational warnings, and omit the repeated failure sentence before corrections
- Keep one multipart submission and all batch prechecks, stream real file results in order after each atomic save, and retain ordinary form submission as a fallback; never simulate progress or retry automatically after a connection failure
- Prevent duplicate submissions without disabling the file input; retain confirmed results after an interrupted response and mark unfinished files as unconfirmed
- Check request file count, total bytes, and total object count before any saves; treat file size and content errors as local to that file, and retain a separate atomic identifier and quota recheck for each file
- Upload allowances are 5 files, 100 MiB per file, 250 MiB combined, and 1,000 objects per submission; stored JSON quota is 5 GiB per user, with depth 100 and 20 submissions per hourly window unchanged
- Release parsed JSON after each file's batch precheck and process one file at a time; application allowances do not guarantee the current hosting plan's capacity
- Current required top-level fields include `phase`, not `material`, unless code is explicitly changed
- Use the current MiMeDat `phase_name` for phase names in labels, summaries, and search; retain legacy name fallbacks without renaming uploaded JSON or treating phase_id as a name
- `identifier` is not a required upload field: missing, null, or blank values use Ronak's MiMeDat template exactly: clean a copy with remove_empty_entries, concatenate json.dumps(value, sort_keys=True) for non-null mandatory values in the template's fixed order, then take hashlib.md5(...).hexdigest()[:8]
- Hash original field names and values without the metadata compatibility view; keep the template's exact field lookup and list cleanup semantics, including filtering falsy list entries, confined to the hash input; never remove values from stored or exported JSON
- Preserve valid supplied text identifiers; reject malformed values and surrounding whitespace with actionable errors
- Check generated and supplied identifiers against all stored records and the whole upload batch; retain the transactional recheck and never overwrite duplicates
- Do not convert generated IDs to base36, extend collisions, or reuse historical content fingerprints; collisions reject the file through the ordinary duplicate checks
- Recheck all identifiers and quota under the final upload transaction lock, including the generated identifier's JSON byte size; top-level optional metadata is excluded from hashing and existing identifiers are never recalculated automatically
- Keep the historical identifier_fingerprint column and values untouched for compatibility with existing databases; new uploads leave it blank and do not consult it

## Access control rules

- The owner can always view their own data
- Public data can be viewed by other signed-in platform users; it is not anonymous access
- Shared data can be viewed only by explicitly shared users
- Only the owner can delete a data object
- Search results and detail-page access rules must stay consistent
- Never rely only on template-level hiding for security
- Always enforce permissions in Django views
- Curve CSV exports use the plot's available series, preserve precision and full array lengths, and mark calculated equivalents; shorter columns end with blank cells
- A single selected object downloads as CSV; multiple objects download as one CSV per object in a ZIP, with the entire selection checked for access and exportable curves
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
- Detail metadata orders all supplied schema fields by properties declaration order at every level, including fields from the referenced constitutive and microstructure schemas, without prioritizing required fields
- Place supplied top-level $schema, $id, version, type, and description before identifier in that order; show uploaded values, do not add missing header fields, and show description only once
- Omit top-level mechanical_BC, stress, total_strain, and plastic_strain from the metadata list while retaining their visualizations and complete export; same-named nested fields remain visible
- Keep fields not defined at that schema path at the end of their own parent, in relative stored order, without an Additional metadata group; freeform objects retain stored order
- Collapse actual nested objects and object lists, even with one child; never merge flat fields by shared prefixes such as creator_affiliation, creator_institute, and creator_group
- Preserve field names, values, array item order, and complete JSON downloads; only display supplied fields, without adding missing-field placeholders or deriving upload requirements from the display order
- Use current MiMeDat equivalent_stress, equivalent_strain, and equivalent_plastic_strain fields for plots; supplied arrays take precedence and only absent fields may use the existing calculated equivalents
- Detail plot ranges cover the paired sample extrema and the true origin independently, without symmetric expansion; use a positive range for all-zero coordinates and preserve tiny signed values and original sample order, including loops and reversals
- Detail plots use exactly two Cartesian axes through zero with arrows toward positive X and Y and a separate 0 label for each axis; place tick labels beside the actual axes, keep titles outside the plotting area with the Y title vertical, draw curves above axis text, and omit rectangular frames, endpoint circles and interior grid lines
- Detail curve hover detects proximity to the full plotted segments, highlights a real recorded sample with a larger dot, shows its zero-based index and precise X/Y values with units, and clears away from the curve or canvas; never invent interpolated sample values or sort cyclic curves for hit testing
- Display whole cube stress or strain tensor loads with all their steps and components; never interpret a tensor as an X, Y, or Z scalar load or guess a directional arrow
- Whole RVE tensor schematics use the explicitly labeled ij direction/face-normal convention, fixed-length component arrows, and linked numeric matrices; preserve distinct xy/yx values and never infer missing components in the direction view
- Strain shape illustration is opt-in, normalized, and explicitly assumes symmetric small strain with tensor shear; reject incomplete or conflicting reciprocal data for that preview, and never present it as a simulated shape or change stored/exported values
- Tensor load navigation follows the supplied entry order and exact step values; do not invent intermediate steps, combine separate tensor conditions, or simulate time histories from frequency/duration metadata
- Show boundary load numbers with two decimal places and half-up rounding, retaining full integer step values and original stored/exported numbers; label the combined column Loading Type / Mode
- Keep X/Y/Z boundary labels on one line in evenly spaced columns; allow independent load panels to stay open together below their own labels, growing the row without shifting sibling labels or overlapping other rows
- Search result pages should not include delete actions unless explicitly requested
- Preserve the existing visual style unless a change is requested
- Avoid large redesigns unless explicitly requested
- Keep Live Data Objects compact, with natural row heights and a bounded scrolling list; do not stretch rows to fill the screen
- Live Data Objects omits per-row Public badges and shows the total of all public objects, even when only the latest 20 are displayed
- Search results show Public or Private without expanding the row, show the matching total, and place public objects before private ones; retain newest-first ordering within each group

## Charts rules

- Charts defaults to all accessible objects; offer My uploads, Public and Shared with me scopes using the same server-side permissions as detail pages
- Use the shared metadata compatibility view, keep raw JSON out of retained statistical summaries, and never change stored data or exports while computing statistics
- Count each object once per case-insensitive category label; multiple phases, models, descriptions or loading conditions may contribute to multiple labels
- Every chart link refines the current selection with AND conditions on the same object, including repeated labels and numeric intervals; counts must equal the linked result count
- Numeric chart boundaries and drillthrough must share exact Decimal comparisons, retain original extrema and never lose observations after Fahrenheit conversion
- Convert temperatures only from explicit supported units to Kelvin; exclude missing, invalid, unknown-unit and below-zero temperatures instead of using zero
- Grain counts are phase observations, with distinct-object counts for navigation; recognize grain_count and the explicit grain_number alias within orientation, unwrap scalar wrappers and exclude conflicting alternative values
- Availability includes all supported mechanical components and supplied equivalent arrays; calculated equivalents require an absent equivalent field and all six components, following detail-page behavior
- Charts is a dataset coverage and discovery page: show separate materials/microstructure and simulation setup category charts, condition distributions and output availability; each selection narrows the same accessible objects and leads to their detail pages
- Keep individual stress–strain plots and curve downloads on the detail page; do not duplicate a single object's response or infer scientific comparability from aggregate metadata
- Count matching stress–strain availability only when the same component is available in both groups, including supplied or eligible calculated equivalents; keep the legacy result=paired filter's both-groups meaning
- Render aggregate charts as server-side SVG that remains visible without JavaScript; retain units, distinguishable ticks and exact numerical interval links, with each category's coverage and observation denominator visible
- Do not infer physical comparability, combine mixed-unit mechanical extrema, or describe metadata and array availability as a validation pass
- Preserve active filters and permissions in the object list and pagination; invalid filters show errors and no records, never a broader selection
- Keep classification counts, distribution units and denominators visible; preserve empty states, long labels, expandable categories, keyboard operation and ordinary GET navigation without JavaScript
- Verify desktop layout and drillthrough with `DEBUG=True ... manage.py test apps.charts`; the browser test needs Chromium and Node with global WebSocket and must not be skipped

## Search rules

- Keep search practical and understandable
- Basic search and Common filters require all entered whole words, in any order, ignoring case, using the same matcher as new text Data field filters; do not return substrings or records matching only some query words
- Keep the two advanced groups distinct: Common filters for general metadata and Data field filters for preset simulation parameters
- Common filters starts with Identifier, Access, and Owner (uploaded by), followed by Creator, Software, Phase, and Title; keep the `owner` query parameter for Owner and do not add fields without a request
- Top and advanced-panel Search buttons submit the same combined GET form; both Clear links reset all conditions while preserving the panel's expanded or collapsed state, and a keyword is optional
- Data field filters uses 12 preset simulation fields grouped by microstructure, discretization and boundaries, material models, and loading and temperature; do not populate it from arbitrary uploaded JSON keys or duplicate common metadata
- Presets recursively search dicts and arrays using the same case and separator punctuation matching as uploads; `grain_number` is an explicit count alias, not permission to guess arbitrary synonyms
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
