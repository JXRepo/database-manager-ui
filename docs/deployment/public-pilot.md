# Public Pilot Operator Runbook

## Purpose

This runbook covers the minimum operator steps for the public pilot deployment on Render Free with Supabase PostgreSQL and ORCID sign-in.

Uploaded JSON files are parsed into `JSONData` rows. The original uploaded files are not retained after processing.

## Render Environment Variables

Set these non-secret defaults in Render exactly as shown:

| Render key | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12.13` |
| `DEBUG` | `False` |
| `DB_ENGINE` | `postgresql` |
| `DB_PORT` | `5432` |
| `DB_SSLMODE` | `require` |
| `TRUSTED_PROXY_HOPS` | `1` |
| `ORCID_BASE_URL` | `https://orcid.org` |

Keep these generated or manually entered only in Render:

| Render key | Source |
| --- | --- |
| `SECRET_KEY` | Render generated value |
| `DB_HOST` | Supabase Session Pooler host |
| `DB_NAME` | `postgres` |
| `DB_USERNAME` | `postgres.<supabase-project-reference>` |
| `DB_PASS` | Supabase database password |
| `ORCID_CLIENT_ID` | ORCID developer application client ID |
| `ORCID_CLIENT_SECRET` | ORCID developer application client secret |
| `ORCID_REDIRECT_URI` | `https://<render-public-host>/settings/orcid/callback/` |

Optional host settings:

- Leave `ALLOWED_HOSTS` blank for the initial Render hostname only
- Leave `CSRF_TRUSTED_ORIGINS` blank for the initial Render hostname only
- If you add extra hostnames later, set them as comma-separated values and use HTTPS origins only

## Supabase Session Pooler Mapping

Copy the Supabase Session Pooler values into Render like this:

| Supabase field | Render key |
| --- | --- |
| Host | `DB_HOST` |
| Port `5432` | `DB_PORT` |
| Database `postgres` | `DB_NAME` |
| User `postgres.<project-reference>` | `DB_USERNAME` |
| Password | `DB_PASS` |
| SSL mode `require` | `DB_SSLMODE` |

Use the IPv4 Session Pooler, not a direct connection string. Do not commit, print, or paste real secrets into repository files.

## ORCID Configuration

The production ORCID base URL is `https://orcid.org`.

The callback must match exactly, including HTTPS and the trailing slash:

```text
https://<render-public-host>/settings/orcid/callback/
```

Set the same exact URL in both:

- Render `ORCID_REDIRECT_URI`
- ORCID Developer Tools redirect URI configuration

## First Administrator Creation

Create the first administrator only from a trusted local shell that uses the same production Supabase connection as Render.

Do not put `SECRET_KEY`, `DB_PASS`, or the administrator password on the command line. Command-line arguments can leak into shell history and process listings. Even environment variables can be visible to other trusted processes under the same account while the command is running, so use a trusted local shell, keep the session private, and unset secrets immediately afterward.

ORCID credentials are not needed for `createsuperuser`.

Example local flow with placeholders only:

```bash
cd /absolute/path/to/public-pilot

read -rp "Supabase Session Pooler host: " DB_HOST
read -rp "Supabase DB username (postgres.<project-reference>): " DB_USERNAME
read -rsp "Supabase DB password: " DB_PASS
echo

SECRET_KEY="$(
  .venv/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
)"

export DEBUG=False
export SECRET_KEY
export DB_ENGINE=postgresql
export DB_HOST
export DB_PORT=5432
export DB_NAME=postgres
export DB_USERNAME
export DB_PASS
export ALLOWED_HOSTS='<render-public-host>'
export CSRF_TRUSTED_ORIGINS='https://<render-public-host>'

.venv/bin/python manage.py createsuperuser

unset DB_PASS SECRET_KEY DB_HOST DB_USERNAME
```

Do not add any public bootstrap route for administrator creation.

## Free-Tier Pilot Caveats

- Render Free can sleep after idle time, so the first request after inactivity can be slow
- Supabase Free can pause low-activity projects
- Neither free tier provides a production-grade uptime or backup guarantee for this pilot
- No pilot data should be assumed recoverable if the Supabase project is deleted

## Before Ending the Pilot

Before intentionally ending the pilot, export the database or explicitly accept deletion of the trial data.

Minimum expectation:

1. Create a full PostgreSQL export from Supabase
2. Store the export in an operator-controlled location
3. Confirm whether the pilot data should be retained or deleted

## Smoke Test Sequence

Run this sequence in two stages:

First deployment:

1. Register a new local account
2. Log in with username and password
3. Log in with ORCID
4. Upload a valid JSON file
5. Search for the uploaded object
6. Share a private object with another user
7. Export selected data

Then run one deliberate redeploy for the persistence check:

8. Trigger a redeploy
9. Confirm the created account still exists
10. Confirm the uploaded/shared data still exists

For later redeploys, repeat the persistence tail and spot checks from steps 8 to 10 rather than repeating the full first-deployment flow every time.

## Operational Notes

- Production requires `DEBUG=False`, a non-default `SECRET_KEY`, and all required `DB_*` values
- The application stores parsed data objects in PostgreSQL with SSL required
- Render build runs dependency install, `collectstatic`, and migrations
- The application should not be used as a long-term archival store during the free pilot
