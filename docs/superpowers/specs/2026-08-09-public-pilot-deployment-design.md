# Public Pilot Deployment Design

## Purpose

Deploy the Django application as a zero-cost public pilot for a small group of
department users. The pilot must preserve data across Render restarts, fail
safely when production configuration is incomplete, and remove legacy public
write paths that are unrelated to the core FAIR data workflow.

This deployment is a public trial, not a production service with an uptime or
backup guarantee. Render Free can sleep when idle, and Supabase Free can pause
low-activity projects.

## Selected Architecture

```text
Browser
  -> Render Free web service
     -> Django 5.2 application, one Gunicorn worker
        -> Supabase PostgreSQL through the IPv4 Session Pooler
        -> ORCID OAuth over HTTPS
```

Render serves the Django application and collected static files. Supabase is
the only persistent application database. Uploaded JSON files are parsed and
stored as `JSONData` rows; original files are not retained on Render's
ephemeral filesystem.

## Runtime and Dependencies

- Use Python 3.12.13 on Render.
- Pin Django 5.2.16, the supported 5.2 LTS security release selected for this
  pilot.
- Pin `psycopg[binary]` 3.3.4 for PostgreSQL connectivity.
- Pin `python-dotenv` 1.2.2 and `requests` 2.33.0 to resolve the direct-dependency
  findings from the existing audit, then run the entire test suite.
- Run a single Gunicorn worker because Render Free provides limited memory and
  CPU.
- Serve Gunicorn access and error logs on standard output and standard error.
- Use the generated and committed CSS assets during the pilot build. Do not run
  the unlocked Yarn dependency graph in Render.

## Database Configuration

Development can use SQLite only when `DEBUG=True`. With `DEBUG=False`, all of
the following values are required and a missing value stops application startup:

```text
DB_ENGINE=postgresql
DB_HOST=<Supabase Session Pooler host>
DB_PORT=5432
DB_NAME=postgres
DB_USERNAME=postgres.<project-reference>
DB_PASS=<database password>
DB_SSLMODE=require
```

The Django connection uses `CONN_MAX_AGE=60`, connection health checks, and
`sslmode=require`. The split environment variables are retained so passwords
with URI-special characters do not require manual percent encoding.

Database secrets are entered only in Render. They are never committed to Git,
written to logs, or copied into documentation.

## Render Build and Start

The Render Blueprint uses the Free plan, the Frankfurt region, and a native
Python runtime. Its build command invokes `bash build.sh`, so the repository's
current script mode is not a deployment blocker.

The build performs these operations in order:

1. Install pinned Python dependencies.
2. Collect static files.
3. Apply committed Django migrations with `migrate --noinput`.

The build never runs `makemigrations`. Render Free does not provide a
pre-deploy command, SSH, or one-off jobs, so build-time migration is the
accepted pilot limitation. Migrations in this phase must remain compatible
with the previously running version.

The start command binds one Gunicorn worker to `0.0.0.0:$PORT` and enables
access and error logs. A lightweight `/healthz/` endpoint confirms that Django
is serving requests without exposing configuration details.

## Production Security Settings

With `DEBUG=False`, the application:

- requires a non-default `SECRET_KEY`;
- restricts `ALLOWED_HOSTS` to configured hosts and Render's external hostname;
- accepts CSRF origins only from configured HTTPS origins;
- trusts Render's forwarded HTTPS scheme;
- redirects HTTP to HTTPS;
- uses secure session and CSRF cookies with `SameSite=Lax`;
- enables HSTS without preload during the pilot;
- uses `X_FRAME_OPTIONS=DENY`;
- never exposes passwords, database DSNs, OAuth codes, or tokens in logs.

## Public Attack-Surface Reduction

The core `JSONData` upload, search, detail, share, and export views remain.
Their existing owner, public, and explicitly shared access rules continue to
be enforced in Django views.

The following legacy routes are disabled because the core workflow does not
use them and they currently permit anonymous or ordinary-user writes:

- dynamic API routes under `/api/`;
- dynamic data-table routes under `/dynamic-dt/` and their create, update,
  delete, filter, and export helpers;
- the dormant generated API include;
- the legacy token endpoint at `/login/jwt/`.

The `apps.dyn_api.helpers` validation module remains available to the upload
workflow even though its public API routes are disabled.

## Open Registration and Resource Boundaries

Ordinary username/password registration remains public. ORCID registration and
login are described in the companion ORCID design.

Public pilot safeguards are configurable in Django settings and default to:

- at most 5 JSON files per upload request;
- at most 10 MiB per file;
- at most 25 MiB across one request;
- at most 100 unwrapped data objects per request;
- at most 100 nested JSON container levels;
- at most 50 MiB of measured JSON payload per user;
- at most 5 registration submissions per source IP per hour;
- at most 10 password login submissions per source IP and normalized username per
  15 minutes;
- at most 20 ORCID login starts per source IP per hour;
- at most 20 upload submissions per authenticated user per hour.

File count and byte limits are checked before parsing. Object-count, nesting,
and user-quota limits are checked before saving. A request that exceeds a
resource limit saves no partial objects and returns a clear message. Ordinary
schema validation retains the existing behavior: valid objects can be saved
while invalid objects are reported. Invalid UTF-8, malformed JSON, and
excessive nesting return user-facing validation errors instead of server
errors.

The size quota uses a stored byte count for each `JSONData` object, measured
from its normalized UTF-8 JSON representation. A data migration backfills the
field for existing objects.

Rate limiting is an abuse-reduction measure for the pilot, not a substitute for
an edge firewall or CAPTCHA. Limits are deliberately high enough for normal
department testing. PostgreSQL stores hashed-identifier fixed-window counters
behind a uniqueness constraint; increments use a database transaction and row
lock, so restarts and concurrent requests cannot reset or bypass the counter.
Expired buckets for the same scope and identifier are removed as new windows
are consumed. Raw client IP addresses are not stored.

## Data Lifecycle and Operations

- Supabase holds all persistent users, sessions, profiles, data objects,
  sharing relations, and notifications.
- No user data is expected to survive deletion of the Supabase project.
- Before the pilot is intentionally ended, the owner either exports a database
  dump or explicitly accepts deletion of the trial data.
- Free-tier backup and uptime limitations are communicated as pilot limits.
- The first administrator is created through a controlled local command using
  the same Supabase connection, never through a public bootstrap route.

## Verification and Acceptance

Before deployment:

- the complete Django test suite passes;
- `check` and `check --deploy` pass without unresolved security warnings;
- migration drift check reports no changes;
- static collection succeeds;
- dependency audit has no known fixable vulnerability in direct dependencies;
- production startup fails when any required database variable is missing;
- legacy dynamic routes return 404;
- upload boundaries fail atomically at their configured limits.

After deployment:

- registration, password login, ORCID login, upload, search, sharing, and export
  complete successfully;
- a redeploy preserves the created account and uploaded data;
- PostgreSQL connections use SSL and the Session Pooler;
- the public hostname and exact ORCID redirect URI use HTTPS;
- a cold start after Render idle sleep is documented for pilot users.

## Non-Goals

- paid availability guarantees, automatic point-in-time recovery, or persistent
  Render disks;
- storing original uploaded files;
- CAPTCHA, email verification, or a complete password-reset email service;
- restoring the legacy dynamic API or dynamic data-table product demo;
- custom domains during the first pilot deployment.
