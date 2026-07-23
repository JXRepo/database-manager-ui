# FAIR Materials Data Platform

A Django-based platform for uploading, validating, browsing, sharing, and exporting
FAIR materials simulation JSON data.

The current target is an internal user-ready MVP. The platform focuses on the
core database workflow, not on ontology, knowledge graph, full Studio
integration, or production AI features.

## Current Scope

- Upload one or more JSON files.
- Unwrap a single object, a list of objects, or a dict with a top-level `data` list.
- Validate required top-level fields before saving.
- Save each valid data object as one `JSONData` record.
- Search accessible data by practical metadata fields.
- View compact detail pages with plots and mechanical boundary condition summaries.
- Manage owned data in My Data.
- Share private data with specific usernames.
- Export accessible or owned selected data objects.

## Access Rules

- Owners can always view and delete their own data.
- Public data (`access_type: "all"`) can be found through Search.
- Private data (`access_type: "c"`) is only visible to the owner unless shared.
- Shared private data is visible to explicitly listed users.
- Permissions are enforced in Django views, not only hidden in templates.

## Required JSON Fields

Uploads currently validate required top-level fields only. Extra fields are
allowed.

Required fields include:

```text
identifier, title, creator, creator_affiliation, date, shared_with, rights,
rights_holder, software, software_version, system, system_version,
processor_specifications, input_path, results_path, RVE_size, RVE_continuity,
discretization_type, discretization_unit_size, discretization_count,
mechanical_BC, phase, stress, total_strain, units
```

Use `phase`, not `material`, unless the schema is explicitly changed later.

Sharing metadata uses usernames:

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

For public data:

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

Create or update `.env` from `env.sample`:

```text
DEBUG=True
SECRET_KEY=<STRONG_KEY_HERE>
```

Install dependencies and prepare the database:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Run the development server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open:

```text
http://127.0.0.1:8000/
```

## Verification

Run the core test suite:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

Check migrations and Django configuration:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
```

## Near-Term Product Priorities

1. Keep upload, validation, search, detail, access control, sharing, and export stable.
2. Add only light microstructure visualization first, using a shared example object.
3. Keep MimDat Studio as a workflow/local tool unless a small maintainable viewer is extracted.
4. Treat ontology, knowledge graph, LLM assistant, and agent features as later enhancements.
