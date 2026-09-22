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
- Signing in or connecting with ORCID fills empty email and institution fields
  from public profile information. It preserves existing values and never uses
  an email match to select or merge accounts. Email must be public and verified
  by ORCID; the primary address is preferred when available. Institution comes
  from one distinct current public employment organization. Missing, private,
  invalid or ambiguous details remain editable in Account Settings. Optional
  profile requests have timeouts and size limits; their failure does not prevent
  sign in. Tokens are used during the callback only and are not stored.
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

- Upload one or more JSON files.
- Unwrap a single object, a list of objects, or a dict with a top-level `data` list.
- Validate required top-level fields before saving.
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

Each selected file has its own status on the right: Waiting, Processing,
Uploaded, or Failed. Only the file currently being checked and saved shows a
spinner; the next file starts after its result is confirmed. Detailed errors
appear together below the form after all files finish.

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

Upload errors follow the selected file order, then the original data object order
within each file. Each object is identified by its title and supplied identifier
when available, with its position in the file for reference. Missing fields,
empty values, identifier problems, and sharing problems appear in separate lists,
each followed by instructions for that issue. Missing or blank identifiers are
assigned automatically and are not reported as errors.

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
underscores, and hyphens: `Grain Count` and `grain_count` are equivalent.
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

Schema validation checks required top-level fields; extra fields are allowed.
Required values cannot be null, blank strings, or empty lists or objects.
Uploads also undergo resource, identifier, and sharing checks.

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

### Data object identifiers

Each saved object has its own top-level `identifier`, alongside `title` and
`creator`. A missing, null, or blank identifier is generated automatically.
A supplied identifier is preserved and must be a JSON string without leading
or trailing whitespace; malformed values produce an error instead of being
silently replaced. Identifiers are compared exactly, including letter case.

Generation follows the required content hashing approach in
[Ronak Shoghi's MiMeDat template](https://github.com/Ronakshoghi/MiMeDat/blob/main/metadata_template.py),
but uses SHA-256 for its internal content fingerprint, not an MD5 prefix.
The public identifier starts at **8 characters**, using **0–9 and a–z**.
If another object with different required content occupies that identifier,
only the new identifier grows, one character at a time, until it is available.
Previously assigned identifiers never change to accommodate new uploads.

The fingerprint input is a JSON mapping of the 24 required fields
above, serialized with sorted keys, compact separators, and ASCII escaping.
Field names and nested content are included; array order, zero, and false values
are preserved. The upload does not remove empty optional values or change other
fields. This is not byte-for-byte compatible with Ronak's eight character IDs;
existing supplied IDs, including hers, are retained.

The complete fingerprint is stored separately from the JSON for generated IDs,
so uploading the same required content again is still reported as a duplicate,
even if its short identifier was extended or a conflicting record was deleted.
Old 64 character SHA-256 identifiers remain recognized without rewriting them.
JSON key order and optional fields such as `description` and `keywords` do not
affect the fingerprint. Different supplied identifiers may still refer to the
same content; user supplied identifiers are not automatically changed.
Reimported JSON with a matching extended identifier is recognized from its
required content even though the exported file does not contain the internal fingerprint.

For reproducibility, candidates use the SHA-256 digest encoded as 50 lowercase
base36 digits, read from the least significant digit first, with zero padding
at the end. The allocator tries prefixes of length 8, 9, and so on up to 50.
If no candidate is available, the upload reports an error rather than overwriting
data. Short IDs depend on existing assignments in this database, not just content;
retain assigned identifiers when moving or exporting data to another installation.

All identifiers, supplied or generated, are checked against every stored record
(including private records), other objects in the same file, and all files in
the submission. Final allocation and duplicate checks share a transaction lock
across uploads, so a newly occupied short ID can be extended safely before saving.
Within a submission, a supplied identifier that repeats an earlier accepted
identifier is reported as a duplicate; supplied values are never silently renamed.
Duplicates are not overwritten; errors identify the filename, object number,
and identifier, with instructions to remove the duplicate or supply another
identifier for a distinct object. Any duplicate rejects its entire file,
including duplicates found during the final transactional recheck. Previously
successful files stay saved, and later files continue to be checked. Distinct content
with an automatically generated short ID is extended instead of rejected.

Generated identifiers are part of the stored JSON, its quota size, and exported
JSON. Internal fingerprints are not added to exported JSON. The original file
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

Initialize the local database and start the development server:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8001
```

On Windows, use:

```powershell
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

Deployment does not require a public GitHub repository. Before making this
repository public, review files and commit history for secrets and personal data,
and read the license and third party notices below.

## Verification

Run the test suite against Django's separate test database:

```bash
.venv/bin/python manage.py test
```

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
