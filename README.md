# FAIR Materials Data Platform

This platform builds on the
[DatabaseManager](https://github.com/Ronakshoghi/DatabaseManager) web application
developed by [Ronak Shoghi](https://github.com/Ronakshoghi).

A Django platform for uploading, validating, searching, sharing, and exporting
materials simulation data as JSON.

The platform is currently a public pilot for a small group of research users.
Development focuses on the core data workflow and access control. Ontology,
knowledge graphs, full Studio integration, and production AI features remain
future enhancements.

## Try the Platform

[Open the pilot website](https://fair-materials-data-hub.onrender.com/).

1. Create an account, or use the ORCID sign in option.
2. Upload a small JSON file that follows the metadata requirements below.
3. Search accessible records, manage your uploads in My Data, and try sharing
   and JSON export.

The first time you enter the platform, a welcome dialog starts a short tour.
Next introduces Search, Upload Data, My Data, and Share in that order, with an
arrow pointing to each sidebar button. Back revisits the previous step; Finish
or Skip tour closes the guide without leaving the current page. Your account
remembers completion or skipping across browsers and future logins.
Existing accounts also receive the guide once when it becomes available. ORCID
accounts finish their required username and password setup before seeing it.
Reopen it using the help icon in the top bar. On small screens, the tour opens
the sidebar temporarily and restores it when closed. The Quick start page
provides the same four descriptions without JavaScript.

Use test data and keep your original files. The pilot is not a permanent archive.
Accounts and data created on a local development server are separate from those
on the hosted website; deploying the code does not copy them to the cloud.

### Accounts

- Usernames contain 1 to 150 characters: letters, numbers, or `@ . + - _`.
  Spaces are not allowed. Registration rejects duplicate usernames, including
  names that differ only in letter case.
- Passwords must contain at least 8 characters. Special characters are allowed,
  but no particular combination of character types is required. Passwords cannot
  consist only of numbers, be commonly used, or be too similar to account details.
- Email is optional. Email verification and email password recovery are not
  available during the pilot.
- Remember me is off by default. Without it, a password or ORCID login lasts
  30 days from sign in, even across browser restarts. Activity does not extend
  this limit. Selecting Remember me starts a persistent session lasting 365 days.
  Normal page visits renew it for another 365 days, at most once a day;
  background refreshes do not renew it. Regular use therefore avoids a fixed
  monthly or quarterly sign in requirement. A remembered session can still
  expire after a long absence, and clearing cookies or security changes may
  require signing in again. Sign out ends the session immediately; always
  sign out on shared or public computers.
  Registration uses the fixed default of 30 days. Sessions without login policy
  metadata receive that default on their next authenticated request.
  Admin login remains separate: it lasts at most 8 hours and normally ends
  when the browser session closes.
- To connect ORCID to an existing platform account, sign in to that account first
  and select Connect ORCID in Account Settings. Signing in directly with an
  unlinked ORCID identity creates a separate account; matching names or email
  addresses do not merge accounts.
- Signing in or connecting with ORCID fills empty name, email, institution,
  department, position, website and research keyword fields from public profile
  information. Name is separate from the login username. Account Settings lets
  users edit all these optional details; existing values are preserved, and an
  email or name match never selects or merges accounts. Email must be public and
  verified by ORCID; the primary address is preferred when available. Name uses
  the published name when available, otherwise the given and family names.
  Website uses the first valid public HTTP or HTTPS link in the researcher's
  preferred order; public keywords are deduplicated in that order.
- Institution comes from one distinct current public employment organization.
  An existing institution restricts department and position imports to matching
  employment records; existing department and position values must also agree.
  Ambiguous roles are left for manual entry. Missing, private, invalid or
  oversized details remain editable in Account Settings. Up to two optional
  requests read the person and employment sections, with timeouts and size
  limits; their failure does not prevent sign in. Tokens are used during the
  callback only and are not stored.
- One verified ORCID iD can belong to only one platform account. Account Settings
  shows Connected and a Disconnect button. Disconnect removes the link directly
  and retains your username, password, account, and uploaded data.
- After signing in with ORCID, accounts without a local password must choose a
  username and enter a password twice before using the platform. This also
  applies to existing accounts that previously used only ORCID. The setup dialog
  cannot be skipped or closed; Sign out is available. These credentials are for
  this website and do not change your ORCID login details.
- Saving your username and password takes you into the platform and leaves ORCID
  connected. Your existing account and data are retained. Later ORCID logins go
  directly into the platform once these credentials have been set.
- Registration and login submissions are rate limited. Repeated attempts can
  temporarily block further submissions.

### Upload and Storage Limits

The application currently enforces these limits:

| Item | Limit |
| --- | --- |
| JSON files per upload submission | 5 |
| Size of each file | 100 MiB |
| Combined file size per submission | 250 MiB |
| Data objects per submission | 1,000 |
| JSON container depth | 100 |
| Stored JSON per user | 5 GiB |
| Upload attempts per user | 20 per hourly window |

One MiB is 1,048,576 bytes; one GiB is 1,024 MiB.
The per-user storage quota counts compact UTF-8 JSON,
not the size of the original files. It is a limit on currently stored data, not
a monthly allowance. Deleting your records frees your personal quota. Failed
upload submissions also count toward the upload rate limit.

The upload page shows these allowances directly from the active settings. On the
hosted service with JavaScript enabled, one multipart submission reports actual transferred bytes,
then a background task reports parsing, completed object checks and atomic file
results. A completed transfer does not mean the data has been saved. Each file is
labelled saved only after its data and task result have committed together.

You can navigate to other platform pages during an upload and return to Upload
for its results. During transfer, a temporary page frame keeps the sending
document alive; once the server accepts the files, the task can be queried from
another page. Reloading, closing the tab or leaving the site before server
receipt can interrupt transfer. No submission or interrupted task is retried
automatically. Ordinary form submission remains available without JavaScript.
Local `runserver` sessions without an upload worker retain the existing NDJSON
upload flow with actual object checking and saving counts; use the Gunicorn
command in the operator runbook to test background uploads locally.

Task status and confirmed outcomes are private to their owner and retained for
seven days. Original files are temporarily staged outside public static files
and deleted after processing. On the current Render service this temporary disk
is ephemeral: a restart or redeploy can interrupt unfinished files. Confirmed
results remain available, and unfinished files are marked unconfirmed rather
than silently repeated. Hosting failures are not resumable uploads.

These are initial application allowances, defined in
[`config/settings.py`](config/settings.py), rather than verified capacity for
the current hosting plan. There is no quota expansion request feature yet.
Large JSON files expand in memory during parsing; production deployment needs
enough worker memory, temporary disk space, and database storage for the actual
data and concurrent users.

### Current Pilot Hosting

The hosted pilot's infrastructure is separate from the application allowances
above. As of September 2026:

- [Supabase Free](https://supabase.com/pricing) provides a 500 MB database shared
  by the whole website. Accounts, indexes, and other database content use part of
  this space. It is not 500 MB per user. The free project can pause after a week
  of inactivity.
- [Render Free](https://render.com/docs/free#spinning-down-on-idle) puts the web
  service to sleep after 15 minutes without inbound traffic. The next visit can
  show a loading page while the service starts, usually for about a minute.

Keep uploads small even if your personal quota has not been reached. A full
database can prevent uploads, registration, and other operations that need to
write data.

## Current Scope

The home page remains available after signing in. Use the sidebar logo or a
Home breadcrumb to return to it without signing out. Its
header and footer show Register and Login buttons before sign-in, then a single
account avatar after sign-in. Clicking it opens Account details, Enter platform,
and Log out; logging out returns directly to the home page. Footer account access
sits between the platform introduction and section links. Get started
opens registration for visitors and the workspace for signed in users. Upload,
search, and data management controls remain inside the workspace.

- Upload one or more JSON files.
- Unwrap individual objects, lists, dictionaries keyed by identifier, and nested collections.
- Validate required top-level fields and applicable nested requirements before saving.
- Save every object in a fully valid file as a separate `JSONData` record.
- Search accessible data by metadata, nested fields, and numeric comparisons.
- View compact detail pages with plots and mechanical boundary condition summaries.
- Manage owned data in My Data.
- Share private data with specific usernames.
- Export an individual data object or a selected list of accessible objects as JSON.

Each data object becomes a separate `JSONData` record, but a JSON file is saved
only when every object in it passes validation. An error in any object rejects
the whole file, including its other valid objects. The original file is not retained.

Every file is checked in the selected order, including files after a failure.
Within each readable file, validation examines every data object and collects
independent field, identifier, and sharing errors. Finding an error prevents that
file from being saved but does not stop checking its remaining objects.

After processing finishes, results below the upload form show every file's status
and all detected errors grouped by file and data object. Fix and resubmit only
failed files; successful files remain saved. A final identifier conflict, quota
failure, or database save error also rejects that whole file while other files
continue. Failed files do not reserve identifiers or consume storage quota.

Both background uploads and the NDJSON upload flow show `Checking 37 / 100`,
then `Saving 70 / 100`, using actual completed work. Fast operations can skip
intermediate displayed counts; final file rows retain `Checked 100 / 100` even
when validation fails. Checking and saving use numbers without a spinner;
reading and processing indicate activity while no object count is available.
Counts appear beside each file, without a second checking counter beneath the
Upload button. The compact file picker grows to fit multiple selected files.
Saving counts remain provisional until the whole file transaction commits.
Only then is the file labelled Uploaded. A private temporary progress file lets
other pages observe saving counts without waiting for that transaction; it
contains no uploaded data and never overrides confirmed database results.
The NDJSON response emits counts during the same checking and save operations.
Updated clients request these events with `X-Upload-Progress: objects`; already
open older pages keep receiving the original file event protocol.
Closing that stream during a save rolls back its current file and notifications,
while keeping earlier committed files. It does not create a background task;
ordinary submissions without JavaScript still receive the final report.
Errors appear directly beneath the form, before upload limits. Identical fixes
across multiple objects appear once, with the affected count or exact positions.
Missing and empty fields use short actions: `Add` and `Fill in`. For example,
100 objects missing the same three fields receive one shared correction line.
Individual objects stay available in an expandable list in their original order;
a single failed object opens immediately. Extra technical reasons can be expanded
without repeating field paths in the main list. All titles, identifiers and
distinct source locations remain available. The final result appears once;
failed file sections go straight to corrections without repeating that nothing
was saved.

The browser sends the selected files in one submission so batch limits are
checked before saving. It then reads progress from the server as each file is
processed. Duplicate submissions and changes to the selection are blocked while
processing. After completion, select files again to start another upload. If the
connection is interrupted, confirmed results stay visible and unfinished files
are marked Unconfirmed; check My Data before retrying. Uploads are never retried
automatically. Browsers without streaming support use the ordinary form and
receive the final results after processing.

Request resource checks run before any files are saved. Exceeding the file count,
combined size, or total object count limits rejects the submission. File size,
JSON syntax, depth, unsupported numeric values, and invalid Unicode errors reject
the affected file while the remaining files continue. Invalid syntax can prevent
the objects inside that file from being read and checked.

The server reads each file to count objects before saving, releases that parsed
data, then reads the current file again for validation and its atomic save.
It does not retain the parsed JSON for the entire submission at once.
The precheck retains only record paths. Recognition stops at a simulation record
instead of treating its nested metadata as more records. Incomplete collection
members remain available for validation; mixed or unrecognizable entries cause
errors rather than silently importing only their valid neighbors. Field names
and values are not converted, and wrapper keys are not substituted for identifiers.

Upload errors follow the selected file order, then the original data object order
within each file. Each object is identified by its title and supplied identifier
when available, with its position in the file for reference. Missing fields,
empty values, identifier problems, and sharing problems remain distinct, with
short correction instructions and complete details on demand. Missing or blank
identifiers are assigned automatically and are not reported as errors.

## Search

The main search box and common Advanced Search fields require every whole word
you enter to appear in the matching record or selected field. Word order and
letter case do not matter. For example, `isotropic` does not match `anisotropic`.
This is the same whole word rule used by new Data field filters.

In **Advanced Search**, **Common filters** starts with Identifier, Access, and
Owner (uploaded by), followed by Creator, Software, Phase, and Title. Owner
matches the platform uploader's username; Creator matches the creator recorded
in the JSON metadata.
The Search buttons above and below the filters submit the same combined search.
Both Clear links reset all conditions while keeping Advanced Search expanded
or collapsed as it was. The main keyword can be left blank.

**Data field filters** uses preset simulation parameters, following the preset search approach in
[Ronak Shoghi's DatabaseManager](https://github.com/Ronakshoghi/DatabaseManager).
The 12 choices are grouped within one dropdown and search these field names:

| Group | Data field | JSON field | Match type |
| --- | --- | --- | --- |
| Microstructure | Texture type | `texture_type` | Text |
| Microstructure | Grain number | `grain_count`, or the count alias `grain_number` | Number |
| Microstructure | Crystal structure | `lattice_structure` | Text |
| Microstructure | Orientation identifier | `orientation_identifier` | Text |
| Discretization and boundaries | Discretization type | `discretization_type` | Text |
| Discretization and boundaries | Discretization count | `discretization_count` | Number |
| Discretization and boundaries | RVE continuity | `RVE_continuity` | Is: Periodic or Non-periodic |
| Material models | Elastic model | `elastic_model_name` | Text |
| Material models | Plastic model | `plastic_model_name` | Text |
| Loading and temperature | Loading type | `loading_type` within `mechanical_BC` | Text |
| Loading and temperature | Loading mode | `loading_mode` within `mechanical_BC` | Text |
| Loading and temperature | Global temperature | `global_temperature` | Number, in K |

Presets recursively traverse objects and arrays, including extra nesting levels,
up to the search depth limit of 32. Field names ignore letter case, whitespace,
underscores, hyphens and other separator punctuation, using the same recognition
as uploads: `Grain Count` and `grain_count` are equivalent.
Only explicit aliases are recognized; arbitrary synonyms are not inferred.
`grain_number` must mean a count, not a grain identifier. Loading fields stay
within mechanical boundary conditions and do not match thermal boundary conditions.
Common metadata such as owner and software version is not duplicated here.
A small synthetic search fixture in `apps/pages/fixtures/search_fields.json`
covers all 12 fields, including `lattice_structure: "FCC"`; it is not a complete
upload template. Local example files, when available, provide additional coverage.

Choose a parameter and enter its value. Text fields automatically require every
entered word; they do not need a Match selection. Numeric fields retain a
comparison dropdown. You can add up to 10 conditions.
All conditions, common fields, and the main search box must match the same data
object. The preset choices are available even before any data is uploaded;
records missing the selected field do not match.

Metadata keywords are included in the main search. Existing bookmarked URLs with
the older `keywords` parameter keep an editable Keywords input while it is active.

- Text presets match **whole words**, ignoring order and letter case. Separate
  search terms with spaces; all terms must appear among the selected field's
  text values. For example, `elasticity isotropic` matches `Isotropic Elasticity`
  but not `Anisotropic Elasticity`. Punctuation within a term is literal, so an
  identifier such as `orientation-123` does not match `orientation-1234`.
  The search does not include parameter names or arbitrary objects.
- Saved **Contains words** and **Equals text** searches retain their previous
  comparisons. Contains words requires all terms but permits substrings;
  Equals text compares a complete value, ignoring letter case. Their Match
  selection stays visible while the saved comparison is active.
- **Match** follows the selected field: counts and temperature offer number
  comparisons, including Greater than or equal to and Less than or equal to;
  identifiers, models, types, and modes use the automatic whole word search.
  **RVE continuity** uses **Is**, with Periodic (`true`) or Non-periodic (`false`).
  Only actual JSON booleans match; strings and zero or one do not.
- Number comparisons support equals, greater or less than, inclusive limits,
  and **Between** with both endpoints included. Numeric strings are accepted;
  booleans and values containing units are not treated as numbers. A comparison
  or range must match one value, not different values for its two bounds.
- **Global temperature** inputs are in kelvin (K). Stored values with explicit
  Kelvin, Celsius, or Fahrenheit units are converted before comparison. The
  nearest enclosing `units.Temperature` declaration takes precedence; units from
  a sibling object are never borrowed. Missing or unknown units and values below
  absolute zero do not match. Negative search bounds are rejected.
- Separate conditions can match different array entries within the same data
  object; they do not require the same phase or boundary condition entry.
  Existing bookmarked JSON paths keep their exact location and original value
  semantics, including raw numeric comparisons without unit conversion. Older
  Ronak field tokens, such as `Grain_Number`, remain usable in existing URLs
  with their original recursive key matching; active legacy fields are marked
  in the form and are not offered as new presets. Retired elastic and plastic
  parameter selectors remain editable under Saved filters when present in a URL,
  retaining their original exact paths and Contains words behavior. These old
  dictionary searches do not bind a parameter name to its particular value.
- Without JavaScript, Match stays visible so a different comparison can be
  selected when changing field types. Use All words for text presets. An
  incompatible comparison produces an error and must be corrected before searching.
- Invalid or incomplete conditions show an error and do not run a broader search.
- **Clear** resets the search, errors, and results while preserving whether the
  Advanced Search panel is open. Submitted conditions remain in the URL, so browser
  refresh and bookmarks preserve them. Do not put secrets in search terms.

Results only include records you own, public records, and private records
explicitly shared with you. Public results appear before private results, with
the newest uploads first within each group. Each result shows Public or Private
without expanding it, and the Search Results heading shows the total number of
matching objects. **Live Data Objects** is a separate, compact feed of
the latest 20 public uploads; it excludes all private data, including your own
and data shared with you. Its total counts all public objects, including those
beyond the latest 20, and refreshes with the list every ten seconds while the
page is visible. Individual feed rows omit the repeated Public badge.
It is not filtered by the search form. Longer feeds
scroll within the panel rather than stretching each card.
Search scans stored JSON one record at a time and retains display summaries for
matches rather than every original payload. It still reads the accessible data
in the application; this is not an indexed search designed for large datasets.

## Charts

The Charts page provides a dataset overview for two scopes. **Public database**
is the default and includes all public objects in the database. **My data**
includes only the signed-in user's public uploads; **Include private data** adds
that user's private uploads. Received private shares are excluded. Public access
still requires a platform account. Other users' private records never contribute
to statistics or linked lists. Old scope=all and scope=shared bookmarks redirect
to Public database while preserving valid selections.

The default page starts with four simple totals: **Data objects**,
**Material phases**, **Texture types** and **Objects with stress–strain data**.
Phase and texture totals count distinct reported names, ignoring case, rather
than phase observations. Stress–strain availability counts objects with matching
components, not individual curves. All four totals describe the current
accessible selection; missing names contribute no category. **View data** beside
Data scope links to a separate page of matching objects.
Eight cards are visible directly, in four pairs:

- **Phase** counts objects for each phase name with a horizontal lollipop chart:
  thin lines end in dots, with counts and percentages of all selected objects
  beside them, for example `20 (40%)`. Expanded categories use the same labels.
- **Stress–strain coverage** uses a donut chart for the exhaustive, disjoint
  classes with and without matching components.
- **Constitutive models** compares reported elastic and plastic model names
  with separately colored horizontal bars. Each family counts objects per name;
  the coverage denominator counts objects reporting either family.
- **Loading types & modes** uses a heatmap of type and mode combinations reported
  together in the same mechanical boundary entry. Each object counts once per
  combination, even when several entries repeat it. Incomplete or nontext pairs
  do not enter the matrix or its axes. Hover over a cell to read the pair and its count.
  Mode is centered above the columns; Type is vertical and centered beside the rows.
  Both titles use the same gap from the names. The type label column fits its text
  so short names do not leave a large blank area beside Type.
- **Temperature** shows a histogram in kelvin. The header shows objects with a
  usable temperature out of all selected objects. Median and Min–max include the
  K unit; Min–max displays both extrema, including `298–298 K` for a constant value.
  The chart uses 12px text at its maximum width of 420px, with Objects vertical
  beside the count axis and equal gaps between the two axis titles and their ticks.
- **Grain number** shows a box plot of phase observations. Quartiles use linear
  interpolation at positions `(n - 1) × p`, where `p` is 0.25 or 0.75; the median
  is the central observation or the mean of the two central observations.
  Whiskers show the actual minimum and maximum, with no outlier classification.
  A constant value is shown as one point, with no whiskers or box legend.
  The header shows objects with a usable grain number out of all selected objects;
  the caption keeps the phase and object counts distinct. Min–max displays both
  extrema, including `343–343` for a constant value. Hover details report the
  quartiles, median, actual extrema and observation counts.
- **Texture types** uses independently sized bubbles; circle area is
  proportional to object count, rather than a share of a disjoint whole.
- **Software** compares reported software names with vertical columns.

There is no independent Filters form or chart-category selector. Chart marks,
category labels and the coverage legend show information on hover. Clicking them
does not navigate, add conditions or reload the page. Existing bookmarked
conditions appear with individual removal links and **Clear selection**.
Bookmarked conditions combine with AND on the same accessible object, including
repeated labels within one category and numeric intervals. All charts describe
the resulting selection.
Scope changes reset conditions and pagination. Valid private inclusion survives
bookmarked navigation, removal, clearing and pagination. Existing category, range,
result and note bookmarks retain their original filtering semantics; invalid
conditions show errors and no records rather than broadening the selection.
Loading type and mode bookmarks still match labels across the same object;
heatmap counts require the labels together in one boundary entry.
Invalid numeric intervals are also individually removable. Repeated scope or
private-inclusion parameters stay invalid when removing another condition.

Each chart retains its denominator and units. Per-card **Data table** sections
are omitted. Hover over marks or labels to read full category names, exact
counts and percentages. **More categories** appears only when a category chart
has more than six labels; it expands a bounded scrolling chart of the remaining
categories. Loading initially shows up to six types and four modes;
**More combinations** shows observed combinations outside that initial matrix.
These expansions and hover details work without JavaScript. The compact coverage
legend beside the donut retains its two counts and percentages. The dashboard has no
Additional statistics or Source records sections. **View data** opens
**Data objects**, with the same exact
selection, scope, private inclusion and pagination; object titles open detail
pages, and **Back to Charts** returns to the selected statistics. Existing
show=objects links use this page. Historical model, loading, discretization,
equivalent-output and note filters remain valid in bookmarked URLs. Data with
no usable temperature or grain number retain explicit empty
chart cards instead of a fabricated value.

Category counts deduplicate each object per case-insensitive label. Multiple
phases, software descriptions, models or loading conditions can contribute to
several labels, so their percentages can sum to more than 100%; they use bars,
lollipops, independent bubbles, a heatmap or tables, never a misleading
composition pie. Output availability includes all
supported components and supplied equivalent arrays. Calculated equivalents
require an absent equivalent field and all six components, following the detail
page. Matching stress–strain requires a common component in both groups; the
legacy result=paired filter continues to mean both groups are present.

Numeric histograms retain exact Decimal boundaries, equal-width intervals,
empty bins and an inclusive final maximum. A constant value has one frequency
column in the temperature histogram or one point in the grain box plot.
Temperatures convert only from explicit supported Kelvin, Celsius or
Fahrenheit units; missing, unknown, invalid and below-zero values are excluded.
Grain counts are phase observations; bookmarked intervals deduplicate matching records.
Numeric summaries retain original extrema and precise interval bounds, including
large neighboring integers and fractional medians and quartiles; labels may use
a visible axis or interval offset for readability. Category and grain interval
bookmarks count distinct objects; the box describes phase observations.
Existing numeric interval bookmarks keep their exact comparisons.

Plots use server-rendered SVG with native hover details, remain visible without
JavaScript, and need no chart-library network dependency. Statistics read shared
metadata compatibility summaries without retaining raw curves. Functional
conflicts never select a value silently. Notes and availability are not upload
validation results or evidence of physical comparability. Individual response
curves and downloads stay on the detail page; stored JSON and exports are
unchanged.

## Data Object Details

The FAIR Data Assistant button is available inside the signed in workspace,
including search, upload, details, My Data, and account settings. It is absent
from the home, login, and registration pages. Upload and detail pages retain
their specific suggestions and data context; questions require authentication
and data access.

Press Enter to send a question or Shift+Enter to add a new line. Confirming
an input-method composition does not send. **Browse help topics** stays below
the input beside **Send**.

The assistant matches English and Chinese questions to maintained platform
answers with a small multilingual model running inside Django. It uses no
external model API, API key, model training or live support handoff. Answers
remain in English. **Browse help topics** opens nine general categories:
Getting started, Prepare data, Upload, Search, Access and sharing, My Data,
Reading data and plots, Charts, and Account. Current object is also available
on detail pages. There are 76 prepared guides and six current-object summaries.
Each category offers at most six questions per page, with page buttons and
`more`/`back` navigation. Exact menu choices work even when semantic matching
is unavailable. See the [coverage and maintenance guide](docs/assistant-coverage.md).

Ambiguous questions offer choices: `data form` asks about JSON format or the
upload form; `format`, `which fields?` and `how big?` can continue that conversation.
Numbered choices such as `the second one` refer to the last suggested questions,
up to the sixth question on a category page. Password and ORCID questions can
offer more specific choices before answering. Answers link to relevant pages
and suggest the next related tasks, including troubleshooting and current limits.
A complete new question can change topics. Low confidence produces clarification
or platform help choices; this is not a general chat or answer generation model.

The answer catalogue and representative phrases live in
[`apps/pages/assistant_knowledge.py`](apps/pages/assistant_knowledge.py), grounded
in these platform rules and the bundled schema profile. Upload allowances come
from active settings. [`apps/pages/assistant.py`](apps/pages/assistant.py) handles
matching and follow-ups. Object summaries recheck access on every request.
The assistant does not execute searches, modify data, fit curves or inspect
selected upload files. Questions and object contents are never sent to a model
service or retained in its example cache. Page memory holds the visible messages
and a signed topic/choice token bound to the user and current object, expiring
after 30 minutes. Browse help topics resets the topic; navigation or refresh
clears the page conversation.

Run `manage.py prepare_assistant_model` during setup as described below. It fetches
about 118 MiB of public model assets, pinned and SHA-256 checked in
[`apps/pages/assistant_semantics.py`](apps/pages/assistant_semantics.py), into the
ignored `.assistant-models/` directory. The model is the Apache-2.0 licensed
[multilingual MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2),
using its quantized ONNX export and SentencePiece vocabulary. Questions never
trigger a download. See the [operator runbook](docs/deployment/public-pilot.md#local-assistant-model)
for deployment and resource limits.

Standard field names follow the
[MiMeDat schema, version 1.2.0](https://github.com/Ronakshoghi/MiMeDat/blob/511cb98b02270d7f31b55243ff49cfef6c7b240d/microstructure_sensitive_mechanical_metadata_schema.json):
`phase_name`, `processor_specifications`, and the underscore-separated names
inside `origin`, such as `software_version` and `input_path`.

Supplied top-level `$schema`, `$id`, `version`, `type`, and `description` appear
first, in that order, matching the schema document's opening fields. These rows
show uploaded values, not values copied from the schema. `description` appears
only once, near the beginning of the list.

The remaining fields follow the schema's `properties` order at every level,
whether required or optional. For example, `identifier` precedes `title`,
and the creator fields stay together. Nested order also covers the general
constitutive model and microstructure schemas referenced by the main schema.
Only supplied fields are shown; missing fields are not added as placeholders.

Fields not defined at that path follow the schema fields at the end of the same
object, retaining their relative stored order. They stay inside their original
parent without an Additional metadata group. Freeform parameter objects retain
their stored field order. Display ordering uses local field lists and does not
fetch uploaded schema URLs or validate nested data. Object key order in JSON is
not a validation requirement; the schema's declaration order is used here as a
consistent presentation rule.

Top level `mechanical_BC`, `stress`, `total_strain`, and `plastic_strain` are
omitted from the metadata list because the boundary condition view and plots
below use them. Fields with those names inside another object remain visible.

Collapsible groups follow actual JSON objects and arrays of objects, including
objects with only one child. Flat fields such as creator_affiliation,
creator_institute, and creator_group remain separate; shared name prefixes do
not create groups. Arrays containing multiple objects keep separate Item 1,
Item 2 groups. Short scalar lists stay inline, while long numeric and complex
arrays offer Show values. Strings, numbers, booleans, nulls, empty containers,
and mixed arrays remain displayable.
Expanded numeric arrays flow horizontally and wrap to fit the available width,
preserving all values and their order.

Each metadata group shares an aligned field-name and value column. Field names
use their natural width up to 48% of the group, leaving space for values; long
names and content wrap within their columns. Compact indentation and subtle
vertical guides keep expanded nesting readable without wasting page width.

Original names, literal punctuation, values, and array item order are preserved.
Download JSON exports the complete stored object, including the four fields
omitted from the metadata list and any values not used by the visualizations.
Upload validation and access rules are unchanged.

Plots read supplied `stress.equivalent_stress`,
`total_strain.equivalent_strain`, and
`plastic_strain.equivalent_plastic_strain` arrays. Supplied curves take precedence
over calculated values. Only absent equivalent fields are supplemented from
complete tensor components using the existing formulas; an explicitly empty
equivalent array stays empty.

The plot section can download the current X/Y series, all available curves, or
any checked subset as CSV. CSV columns use full field paths and available units;
calculated equivalent curves are marked `(calculated)`. Numeric values retain
their stored precision. The `index` column starts at zero and refers to array
position, not time. Columns of different lengths keep every sample, with blank
cells at the end of shorter columns; no interpolation or resampling is applied.

My Data and search results also offer CSV export for selected objects. One
object downloads as one CSV; multiple objects download as a ZIP containing one
CSV per object, with identifiers (or titles) and record IDs in the filenames.
These are UTF-8 CSV files, not Excel workbooks. Every selected object must still
be accessible and contain an exportable curve; otherwise the full download is
rejected with a message instead of silently omitting objects. Existing JSON and
PNG downloads remain available.

Detail curves use the Charts palette, with a blue line and no endpoint markers
or grid lines. Their canvas is centered at a fixed 720 × 480 CSS pixels on
desktop, with width capped by the available panel space to prevent overflow.
Two Cartesian axes intersect at the actual origin, with arrows
pointing right and up and a separate zero label for each axis; no rectangular
frame is drawn. Each range covers the paired data extrema and zero independently,
without making signed ranges symmetric. An entirely zero coordinate uses a
positive range. Small signed values retain their actual signs and scale.
Tick labels sit beside the actual axes, on the side closest to the plotting
edge; titles stay outside the plotting area, with a vertical Y title. Axis text
is drawn before the curve and has no background masks. Curves retain original
sample order, including loops and reversals, selected variables, raw values and
all exports.

Moving within 16 pixels of a detail curve highlights the nearest recorded
sample on that segment with a larger blue dot and white border. The tooltip
shows its zero-based sample index and exact X/Y numbers with variable names and
units. It also works between sparse samples and on loops without sorting the
curve or creating interpolated values. Moving away from the curve, into the
canvas margins, or outside the canvas clears the highlight and tooltip.

Plots and downloaded PNGs omit the figure title. Axis labels italicize only the
scalar symbols sigma and epsilon.
Subscripts, descriptions, and units stay upright, including in downloaded PNGs.
Axis labels and units use 18px text with 13px subscripts. Stress units come from
the uploaded `units.Stress` value. For total and plastic strain, an explicit
`units.Strain` value of `1` is displayed as `(-)` on the axes. Missing units stay
unspecified; stored JSON and CSV exports retain their existing values and format.
Variable selectors, tooltips, and raw-value summaries use matching mathematical
italic glyphs for these two symbols; field keys and plotted values are unchanged.

Mechanical boundary conditions include the supplied load `step`. Whole RVE
stress and strain tensors have a component matrix linked to the cube. Choose a
boundary condition and load entry, or move the slider through entries in their
supplied order. This selects recorded entries, without interpolating a loading
history from frequency or duration. Select a component to isolate it; hover over
a value or arrow to highlight its counterpart. Normal and shear filters help
separate pull/push directions from sideways loading. All supplied load details
remain available in the table, including without JavaScript.

The direction schematic explicitly uses `ij` for direction `i` on faces normal
to `j`, with outward arrows for positive normal values. It shows supplied
components independently, including unequal `xy` and `yx`, and does not claim
to reconstruct the actual tractions on the simulation boundary. Arrow lengths
are fixed; the matrix and exact values in tooltips carry the magnitudes.
Zero values produce no arrows; missing and invalid components are identified
without being replaced by zero or mirrored. Stress and strain units come from
the uploaded units metadata; dimensionless strain `1` appears as `(-)`.

Strain directions are labeled as guides, not forces. An optional shape
illustration assumes symmetric small strain with tensor shear and no rigid
rotation. Only in this explicitly selected preview, omitted reciprocal terms
are mirrored from the six required components. Conflicting reciprocal values
or incomplete components disable the shape preview. Deformation is normalized
for readability, not a calculated or to-scale simulation result; stored values
and exports are unchanged. These distinctions follow the difference between
[stress components](https://www.comsol.com/multiphysics/stress-and-equations-of-motion)
and [deformation measures](https://doc.comsol.com/6.3/doc/com.comsol.help.sme/sme_ug_theory.06.009.html).

Scalar point, edge and face force/displacement loads retain their axis display.
The table labels the combined column `Loading Type / Mode`. X/Y/Z labels stay on
one line in evenly spaced columns. Load details expand independently below their
own labels, so multiple panels can stay open together. The row grows to fit the
panels without moving sibling labels or covering other rows; click a label again
to close its panel. The wider table allocates most space to Constraints.
Numeric load details,
including tensor components, display two decimal places with half-up rounding;
`step` retains its complete integer value. Stored values, arrows, curves, and
JSON downloads use the original numbers.

Detail display tests use a synthetic example embedded in the test suite, so they
do not depend on a local uploaded JSON file or skip when that file is removed.

## My Data

My Data lists only your own uploads, with the newest first. Use the **Access**,
**Software**, **Phase**, and **Creator** dropdowns to narrow the list before
opening an object. Creator refers to the creator recorded in the JSON metadata,
not the platform uploader. Private includes your private objects shared with
other users.

Software, phase, and creator options come from your uploaded data. Text values
ignore case and surrounding whitespace; each selected value must match a complete
name. Lists contribute individual names, and named metadata objects contribute
their name rather than their parameter values. Every active filter must match
the same object.

Each option shows how many objects match it together with the other selected
filters. The result count shows matching objects out of all your uploads.
Changing a dropdown updates the list; **Clear** restores all uploads. Filters
remain in the URL for refresh and bookmarks. Without JavaScript, use **Filter**
to apply the selections. Bulk selection applies to the objects in the current
list, and existing download and delete actions remain available.

## Access Rules

- Owners can always view and delete their own data.
- Public data (`access_type: "all"`) can be found through Search by other signed-in users.
- Private data (`access_type: "c"`) is only visible to the owner unless shared.
- Shared private data is visible to explicitly listed users.
- Permissions are enforced in Django views, not only hidden in templates.

Here, public access refers to platform users, not anonymous browsing. Access
settings do not grant a copyright license to reuse a dataset; check its rights
metadata separately.

## Required JSON Fields

The upload validator checks the 24 top-level fields below, plus nested and
conditional `required` rules from the bundled MiMeDat 1.2.0 snapshot and its
constitutive and microstructure references. The `jsonschema` library executes
a required field profile, including the container structures needed to reach
those fields. This is not full validation of every numeric, enum or optional
property constraint in the original schema. Extra fields remain allowed.

Before checking these requirements, the platform recognizes schema field names
independently of case and separator punctuation: `Date`, `DATE` and `date` match,
as do `input_path`, `Input Path` and `input-path`. Matching stays within each
field's parent; it does not search unrelated subtrees or guess synonyms such as
`Material` for `phase`. `processor_specification`, `CPU_specifications` and
`CPU_specification` also satisfy `processor_specifications`.

Descriptive fields additionally accept names containing all their words, in any
order, with extra words, simple trailing-s plurals and camel case. For example,
`processor_specification_of`, `Specifications of Processor` and
`processorSpecificationOf` satisfy the same requirement. Supported descriptions
are `title`, `creator`, `creator_affiliation`, `date`, `rights`, `rights_holder`,
`software`, `software_version`, `system`, `system_version`,
`processor_specifications`, `input_path`, `results_path`, `phase_name` and
`texture_type`, only where the schema defines them. Words must occur in one
field name at the correct parent. Exact schema names take precedence; more
specific names remain distinct, so `system_version` cannot supply `system`,
and `creator_affiliation` cannot supply `creator`. A name equally matching two
different requirements does not fill either automatically.

Multiple matching descriptions are accepted even when their values differ.
At least one nonempty match satisfies the requirement; all-empty matches still
produce an error. Lookup views combine the distinct supplied descriptions for
search and summaries. Detail rows, storage and JSON exports retain every
original field and value, including empty alternatives. Matching description
rows share the schema field's display position and keep their relative order.
Units, sharing permissions, identifiers, numeric and structural fields, load
components and curve arrays keep their existing exact-name and conflict rules.
Keyword matching never chooses a permission, unit or tensor value.

Text containing a finite number is accepted at known numeric fields, including
`magnitude`, tensor components and curve arrays. For example, `" 1.5\n"` is read
as `1.5`; words, unit annotations and nonfinite magnitudes remain invalid.
Known enumerated values also tolerate case and surrounding whitespace.
At known scalar or object fields, one or more single-item list wrappers are also
recognized: `magnitude: ["1.5"]` and `magnitude: [["1.5"]]` both mean `1.5`.
The same applies to individual entries where an array expects scalars or objects.
Genuine arrays, including a curve with only one point, retain their list shape;
multiple values are never reduced to the first item, and unknown metadata keeps
its structure. Required values are checked after removing wrappers, so `[""]`
does not satisfy a required scalar field. Wrapped supplied identifiers retain
their exact text and participate in all duplicate checks. When a blank identifier
is filled automatically, its existing single-item wrappers are retained.
Sharing accepts `"all"`, `["all"]`, `"c"`, `["c"]`, the usual permission objects,
and a single explicit flag such as `{"all": true}`, including single-item wrappers
around entries and their values. A username object without
`access_type` remains private. Permission tokens must match completely:
`"not all"`, comments mentioning `all`, and usernames containing `all` do not
make data public. Username lookup and existing sharing restrictions still apply.

This recognition is also used for search summaries, filters, detail plots and
curve exports. Original field spellings, values and array order remain in stored
JSON and JSON downloads. Metadata labels retain those spellings. A valid JSON
document is still required; this compatibility does not imply that its original
representation passes an external validator's full schema.
The implementation is in [metadata compatibility](apps/dyn_api/metadata_compat.py).

Required values cannot be null, blank strings (including whitespace), or empty
lists or objects. Zero and false are not empty. Conditional requirements activate
only when their controlling fields are supplied and the condition matches.
Optional empty fields are preserved and do not block uploads. This includes an
empty optional parent: its children are checked once it has content. A nonempty
list of objects does activate the required rules for every list entry.
For example, mechanical `applied_load` is optional, but each supplied load entry
requires a nonempty `magnitude`. A loaded thermal condition requires both
`loading_mode` and `applied_load`. A tensor magnitude requires its six declared
components. `total_strain: {}` is rejected, without inventing a requirement for
any particular strain curve that the schema's `required` list does not specify.

See [the required field validator](apps/dyn_api/required_schema.py) and
[pinned source URLs and checksums](apps/dyn_api/schemas/sources.json).
Validation runs offline against these trusted files, never against an uploaded
`$schema` URL or an external validation website. Updates require a reviewed
snapshot change. Uploads also undergo the existing resource, identifier, and
sharing checks; this change does not add group sharing or change access rules.

Required fields include:

```text
title, creator, creator_affiliation, date, shared_with, rights,
rights_holder, software, software_version, system, system_version,
processor_specifications, input_path, results_path, RVE_size, RVE_continuity,
discretization_type, discretization_unit_size, discretization_count,
mechanical_BC, phase, stress, total_strain, units
```

Use `phase`, not `material`. See the
[validation implementation](apps/dyn_api/helpers.py) for the current required
fields.

Use `phase_name` for each phase's name, following the current MiMeDat schema.
Charts, My Data, and assistant answers prefer it when legacy name fields are
also present, and Common Phase search recognizes it alongside existing search
values. Older `phase_identifier` values remain readable for compatibility;
uploaded field names, stored JSON, and downloads are not renamed.

### Data object identifiers

Each saved object has its own top-level `identifier`, alongside `title` and
`creator`. A missing, null, or blank identifier is generated automatically.
A supplied identifier is preserved and must be a JSON string without leading
or trailing whitespace; malformed values produce an error instead of being
silently replaced. Identifiers are compared exactly, including letter case.

Generation uses the exact calculation in
[Ronak Shoghi's MiMeDat template](https://github.com/Ronakshoghi/MiMeDat/blob/main/metadata_template.py),
checked on September 28, 2026. On a separate copy, apply the template's
`remove_empty_entries`, then visit the 24 `mandatory_fields` in their declared
order. For each non-null value, append `json.dumps(value, sort_keys=True)` using
Python's default serialization settings. Encode the combined text as UTF-8,
compute MD5, and take the first **8 lowercase hexadecimal characters (0–9, a–f)**.
There is no base36 conversion, collision extension, or choice based on database contents.

This calculation uses original field names and values, independently of the
upload validator's compatibility view. Numeric strings and singleton lists are
not normalized for hashing. Exact mandatory names are used; for example, the
current template lists `processor_specifications`, so `CPU_specifications` is
accepted by upload validation but does not enter the reference hash under that
alias. A file using alternative names for every mandatory field produces the
template's hash of empty input. JSON object key order and optional top-level fields
such as `description` and `keywords` do not affect the identifier.

The template's cleanup removes empty containers and null values. Its list filter
also removes falsy entries such as `0`, `false`, and empty strings. This behavior
is reproduced only for the hash input: stored curves, optional blanks and all
other uploaded metadata remain intact in storage and JSON exports.

Historical identifiers and their stored `identifier_fingerprint` values are
left untouched. New uploads do not create or consult these old SHA-256 content
fingerprints. Re-uploading old content without its assigned identifier therefore
uses the new calculation; retain the identifier when importing an existing record.
The separate `identifier_lookup` digest still supports duplicate checks for
alternative identifier field spellings without changing their text. Migration
`0014_jsondata_identifier_lookup` provides this internal index, with a JSON
lookup fallback for older canonical records. No new migration is needed.

All identifiers, supplied or generated, are checked against every stored record
(including private records), other objects in the same file, and all files in
the submission. Final duplicate and quota checks share a transaction lock across
uploads. Any repeated identifier, including an MD5 prefix collision between
different objects, is reported as a duplicate without changing the identifier.
Duplicates are not overwritten; errors identify the filename, object number,
and identifier, with instructions to remove the duplicate or supply another
identifier for a distinct object. Any duplicate rejects its entire file,
including duplicates found during the final transactional recheck. Previously
successful files stay saved, and later files continue to be checked.

Generated identifiers are part of the stored JSON, its quota size, and exported
JSON. Internal lookup values are not added to exported JSON. The original file
on the user's computer and previously stored records are not modified.

### Sharing metadata

The following examples show only the `shared_with` metadata. They are not complete
upload files; the other required fields must also be present.

For access by the owner only:

```json
{
  "shared_with": [
    {
      "access_type": "c"
    }
  ]
}
```

To share privately, use an existing platform username other than your own:

```json
{
  "shared_with": [
    {
      "access_type": "c",
      "username": "viewer"
    }
  ]
}
```

For public data, omit `username`:

```json
{
  "shared_with": [
    {
      "access_type": "all"
    }
  ]
}
```

## Local Setup

Python 3.12 is recommended to match the Render deployment. The application uses
Django 5.2; exact dependency versions are pinned in
[`requirements.txt`](requirements.txt).

Clone this repository and open its directory. Create a virtual environment and
install the dependencies:

### Linux or macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Development Configuration

If `.env` does not already exist, create it from [`env.sample`](env.sample). Do not
overwrite an existing configuration. Set a random secret key for your local
installation in place of the placeholder:

```text
DEBUG=True
SECRET_KEY=<STRONG_KEY_HERE>
```

With `DEBUG=True`, the application uses the local `db.sqlite3` database. Cloud
database settings are not needed for ordinary local development. Do not use
`DEBUG=True` for a public deployment or commit `.env` to GitHub.

Prepare the assistant model, initialize the local database and start the server.
The model setup needs network access to Hugging Face but no account or API key;
repeating it reuses verified files:

```bash
.venv/bin/python manage.py prepare_assistant_model
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8001
```

On Windows, use:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_assistant_model
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Open [http://127.0.0.1:8001/](http://127.0.0.1:8001/) and create an ordinary account
through the registration page. An administrator account is optional; create one
locally with:

```bash
.venv/bin/python manage.py createsuperuser
```

On Windows, replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`.

ORCID is optional for local development. It requires a client ID, client secret,
and a registered redirect URI for the instance you are running. Do not reuse the
hosted callback URL for a local server.

## Hosted Deployment

The pilot runs on Render with an external Supabase PostgreSQL database. See
[`render.yaml`](render.yaml), [`build.sh`](build.sh), and the
[public pilot operator runbook](docs/deployment/public-pilot.md) for environment
variables, ORCID configuration, administrator setup, and deployment checks.

Production requires `DEBUG=False`, a non-default secret key, and all required
PostgreSQL connection settings. Keep database passwords and ORCID secrets in the
deployment environment, not in repository files.

The hosted service is configured to deploy commits pushed to `main`. Saving or
committing locally does not update the website. After a push, wait for Render to
finish deployment before checking the changes. The build installs dependencies,
collects static files, and applies database migrations; it does not import local
accounts or local data.

The existing Gunicorn command automatically reads [`gunicorn.conf.py`](gunicorn.conf.py),
which runs an independent upload processor and uses four web threads so pages
and status requests remain available during transfers. No extra paid service is
created. Each service boot has its own upload queue identity; a new deployment
cannot claim the previous instance's temporary files. See the operator runbook
for local worker startup and temporary storage capacity settings.

Deployment does not require a public GitHub repository. Before making this
repository public, review files and commit history for secrets and personal data,
and read the license and third party notices below.

## Verification

Run the test suite against Django's separate test database:

```bash
.venv/bin/python manage.py test
```

The detail plot browser test requires Chromium and Node with global `WebSocket`.
It uses the page's existing Chart.js CDN library. For offline checks, set
`CHARTJS_TEST_BUNDLE` to a locally downloaded copy of that library. Optional
`PLOT_SCREENSHOT_DIR` saves desktop screenshots and a downloaded PNG.

Check migrations and Django configuration:

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py check
```

Use the Windows interpreter path shown above when running these commands in
PowerShell. Run these checks with local development settings, not production
database credentials. The [operator runbook](docs/deployment/public-pilot.md#smoke-test-sequence)
also describes manual registration, ORCID, upload, sharing, export, and persistence
checks for the deployed website. Automated tests do not replace those checks.

## Development Priorities

1. Keep upload, validation, search, detail, access control, sharing, and export stable.
2. Add only light microstructure visualization first, using a shared example object.
3. Keep MimDat Studio as a workflow/local tool unless a small maintainable viewer is extracted.
4. Treat ontology, knowledge graph, LLM assistant, and agent features as later enhancements.

## Licenses

The original software code and original modifications developed for FAIR
Materials Data Platform are licensed under the **GNU Affero General Public
License, version 3 only (AGPL-3.0-only)**. See [`LICENSE`](LICENSE) for the complete
license text.

The AGPL covers software used over a network as well as distributed copies.
If you run a modified version of the covered software as a web service,
section 13 requires an offer of its corresponding source code to users
interacting with it. See [GNU's explanation](https://www.gnu.org/licenses/why-affero-gpl.html).

The platform builds on Django Datta Able by App Generator (formerly AppSeed),
with interface components by CodedThemes. Code and assets from other projects
retain their own licenses and copyright notices; the AGPL declaration above
does not relicense them or remove their conditions. In particular, the inherited
AppSeed notice contains conditions beyond the standard MIT text. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the retained notices and
their scope before redistributing bundled components.

Uploaded datasets are separate from the platform's software: their `rights` and
`rights_holder` metadata describe the supplied rights information. Making a record
public in the application does not put it in the public domain or change its
license. The software's AGPL license does not license uploaded data. Upload only
data you have permission to store and share.

## About

FAIR Materials Data Platform supports the practical work of organizing materials
simulation results: keeping data with its metadata, finding accessible records,
and sharing selected results with other researchers. The current focus is a clear
and usable research workflow, not a claim of FAIR certification or scientific
validation.

The application is built with Django, a Bootstrap interface, and a database JSON
field for each data object. Development is maintained in
[`JXRepo/database-manager-ui`](https://github.com/JXRepo/database-manager-ui).

## Disclaimer

This is experimental research software provided for testing and evaluation.
Availability, data preservation, scientific correctness, and fitness for a
particular purpose are not guaranteed. Keep independent copies of your files and
validate results before relying on them in research or other decisions.

Do not use the free pilot as the only copy of important data. Report problems to
the maintainer without including passwords, API keys, personal information, or
unpublished datasets in public reports or screenshots.
