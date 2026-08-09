# Public Pilot Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Django application safe and reproducible as a zero-cost Render Free public pilot backed by Supabase Postgres.

**Architecture:** Render runs one native Python/Gunicorn worker and uses the Supabase Session Pooler over SSL. Django fails closed when production secrets or database settings are missing, removes unused public mutation routes, and adds database-backed rate limits plus atomic per-user upload quota enforcement. Existing valid-object/invalid-object upload behavior remains, but request resource-limit failures save nothing.

**Tech Stack:** Python 3.12.13, Django 5.2.16, PostgreSQL/Supabase, psycopg 3.3.4, Gunicorn 23, WhiteNoise, Render Blueprint.

## Global Constraints

- The deployment target is Render Free in Frankfurt with one Gunicorn worker; this is a public pilot, not availability-guaranteed production.
- Use Supabase Session Pooler, port `5432`, `DB_ENGINE=postgresql`, and `DB_SSLMODE=require`.
- Never commit or print Supabase/ORCID passwords, tokens, or application secrets.
- Production (`DEBUG=False`) must fail closed if `SECRET_KEY` or any required `DB_*` value is absent; SQLite is local-development-only.
- Pin Python `3.12.13`, Django `5.2.16`, `psycopg[binary]` `3.3.4`, `python-dotenv` `1.2.2`, and `requests` `2.33.0`.
- Render build runs install, `collectstatic`, and committed migrations; it never runs `makemigrations` or Yarn.
- Disable `apps.dyn_api.urls`, `apps.dyn_dt.urls`, generated `api.urls`, and `/login/jwt/`; retain `apps.dyn_api.helpers` because core upload validation imports it.
- Upload limits are 5 files/request, 10 MiB/file, 25 MiB combined files/request, 100 unwrapped objects/request, 100 JSON container levels, and 50 MiB stored normalized JSON/user.
- Rate limits are registration 5/IP/hour, password login 10/IP+normalized-username/15 minutes, ORCID start 20/IP/hour, and upload 20/user/hour.
- Rate-limit identifiers use HMAC-SHA256 with `SECRET_KEY`; raw IP addresses and usernames are never stored.
- `apps/pages/migrations/0007_jsondata_size_bytes_and_rate_limit_bucket.py` owns `JSONData.size_bytes` and `RateLimitBucket`; migration `0008` is reserved for ORCID identity.
- All comments and docstrings are English; a docstring's first line must not end in a period.

---

### Task 1: Upgrade and lock the production runtime

**Files:**
- Modify: `requirements.txt`
- Modify: `config/settings.py`
- Test: `apps/pages/test_production_settings.py`

**Interfaces:**
- Produces: `DATABASES["default"]` with SSL, `CONN_MAX_AGE=60`, and `CONN_HEALTH_CHECKS=True`; `PILOT_RATE_LIMITS`; upload limit settings.

- [ ] **Step 1: Write settings behavior tests before changing settings**

Create subprocess-based tests that import `config.settings` with a controlled environment. Assert a complete production environment yields Postgres with `OPTIONS == {"sslmode": "require"}`, while missing `SECRET_KEY` or any of `DB_ENGINE`, `DB_NAME`, `DB_USERNAME`, `DB_PASS`, `DB_HOST`, `DB_PORT` exits nonzero with `ImproperlyConfigured`. Assert `DEBUG=True` without DB variables uses SQLite.

```python
def test_production_database_requires_all_connection_values(self):
    result = self._import_settings(DEBUG="False", SECRET_KEY="test-secret")
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("production database", result.stderr)

def test_local_debug_can_use_sqlite(self):
    result = self._import_settings(DEBUG="True", SECRET_KEY="local-only")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("django.db.backends.sqlite3", result.stdout)
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_production_settings -v 2`

Expected: FAIL because production silently falls back to SQLite and uses insecure defaults.

- [ ] **Step 3: Pin supported dependencies and implement fail-closed settings**

Set the exact pins in `requirements.txt`. In settings, parse `DEBUG` with a false default, require a non-default production secret, require the full DB variable set, and use:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": DB_NAME,
        "USER": DB_USERNAME,
        "PASSWORD": DB_PASS,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        "OPTIONS": {"sslmode": os.getenv("DB_SSLMODE", "require")},
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}
```

Configure exact local or Render hosts, HTTPS proxy handling, SSL redirect, secure cookies, `SESSION_COOKIE_SAMESITE="Lax"`, `X_FRAME_OPTIONS="DENY"`, and one-hour HSTS without preload when `DEBUG=False`. Add:

```python
PILOT_RATE_LIMITS = {
    "registration": {"limit": 5, "window_seconds": 3600},
    "password_login": {"limit": 10, "window_seconds": 900},
    "orcid_start": {"limit": 20, "window_seconds": 3600},
    "upload": {"limit": 20, "window_seconds": 3600},
}
PILOT_MAX_UPLOAD_FILES = 5
PILOT_MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024
PILOT_MAX_UPLOAD_REQUEST_BYTES = 25 * 1024 * 1024
PILOT_MAX_UPLOAD_OBJECTS = 100
PILOT_MAX_JSON_DEPTH = 100
PILOT_MAX_USER_JSON_BYTES = 50 * 1024 * 1024
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1" if not DEBUG else "0"))
```

- [ ] **Step 4: Install the pinned requirements and run focused tests**

Run: `python -m pip install -r requirements.txt && python manage.py test apps.pages.test_production_settings -v 2`

Expected: PASS with no warnings.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config/settings.py apps/pages/test_production_settings.py
git commit -m "build: harden pilot runtime settings"
```

### Task 2: Add persistent byte accounting and database rate-limit buckets

**Files:**
- Modify: `apps/pages/models.py`
- Create: `apps/pages/migrations/0007_jsondata_size_bytes_and_rate_limit_bucket.py`
- Create: `apps/pages/test_pilot_models.py`

**Interfaces:**
- Produces: `JSONData.size_bytes: int`; `RateLimitBucket(scope, identifier_hash, window_seconds, window_id, count, expires_at)` with a unique four-column constraint.

- [ ] **Step 1: Write model and migration tests**

Test that two buckets cannot share `(scope, identifier_hash, window_seconds, window_id)`, that `size_bytes` defaults to zero for direct test fixtures, and that the migration backfill measures compact UTF-8 JSON:

```python
expected = len(json.dumps({"phase": "α"}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
self.assertEqual(migrated_object.size_bytes, expected)
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_pilot_models -v 2`

Expected: FAIL because the field, model, and migration do not exist.

- [ ] **Step 3: Implement the model and migration**

Add:

```python
class RateLimitBucket(models.Model):
    scope = models.CharField(max_length=32)
    identifier_hash = models.CharField(max_length=64)
    window_seconds = models.PositiveIntegerField()
    window_id = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scope", "identifier_hash", "window_seconds", "window_id"),
                name="unique_rate_limit_bucket",
            )
        ]
```

Add `size_bytes = models.PositiveBigIntegerField(default=0)` to `JSONData`. The migration must use a historical model and compact `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`; it must not import runtime model code.

- [ ] **Step 4: Run migrations and focused tests**

Run: `python manage.py migrate && python manage.py test apps.pages.test_pilot_models -v 2`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/pages/models.py apps/pages/migrations/0007_jsondata_size_bytes_and_rate_limit_bucket.py apps/pages/test_pilot_models.py
git commit -m "feat: persist pilot quota and rate limit state"
```

### Task 3: Enforce atomic registration and password-login limits

**Files:**
- Create: `apps/pages/rate_limits.py`
- Create: `apps/pages/auth_views.py`
- Modify: `apps/pages/views.py:89-101`
- Modify: `apps/pages/urls.py:28-39`
- Create: `apps/pages/test_rate_limits.py`

**Interfaces:**
- Produces: `RateLimitDecision(allowed: bool, retry_after_seconds: int)`; `get_client_identifier(request) -> str`; `check_rate_limit(scope, identifier) -> RateLimitDecision`; `consume_rate_limit(scope, identifier) -> RateLimitDecision`; `reset_rate_limit(scope, identifier) -> None`.
- Produces: `RateLimitedLoginView` using the same `SignInForm` and login template.

- [ ] **Step 1: Write failing behavioral tests**

Test literal limits, `Retry-After`, no user creation after the sixth same-IP registration submission, no authentication after the eleventh same IP+casefolded username login submission, HMAC-only persisted identifiers, trusted-proxy parsing, and reset behavior. Use `override_settings(PILOT_RATE_LIMITS=...)` to keep tests small.

```python
@override_settings(PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 3600}})
def test_second_registration_submission_is_rejected_without_creating_user(self):
    first = self.client.post(reverse("register"), self._valid_signup("first"), REMOTE_ADDR="192.0.2.1")
    second = self.client.post(reverse("register"), self._valid_signup("second"), REMOTE_ADDR="192.0.2.1")
    self.assertEqual(first.status_code, 302)
    self.assertEqual(second.status_code, 429)
    self.assertFalse(User.objects.filter(username="second").exists())
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_rate_limits -v 2`

Expected: FAIL because the service and guarded views do not exist.

- [ ] **Step 3: Implement fixed-window database consumption**

Hash `f"{scope}:{identifier}"` using `hmac.new(settings.SECRET_KEY.encode(), ..., hashlib.sha256).hexdigest()`. Derive `window_id = int(now.timestamp()) // window_seconds`. Inside `transaction.atomic()`, `get_or_create` the unique bucket, re-read it with `select_for_update()`, reject at the configured limit, or increment once. Delete expired rows only for the same scope/hash. Return retry seconds through the dataclass.

`get_client_identifier` validates every address with `ipaddress.ip_address`; when `TRUSTED_PROXY_HOPS > 0`, append `REMOTE_ADDR` to the validated `X-Forwarded-For` chain, remove exactly that many rightmost trusted hops, and return the rightmost remaining address. Invalid/missing forwarded chains fall back to valid `REMOTE_ADDR`.

- [ ] **Step 4: Wire registration and login endpoints**

Registration consumes `("registration", get_client_identifier(request))` before form validation. Login consumes `("password_login", f"{get_client_identifier(request)}:{posted_username.strip().casefold()}")` before authentication. On denial return status 429 plus `Retry-After`; on database failure return a generic 503 without creating/authenticating a user.

- [ ] **Step 5: Run focused and existing account tests**

Run: `python manage.py test apps.pages.test_rate_limits apps.pages.tests -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/rate_limits.py apps/pages/auth_views.py apps/pages/views.py apps/pages/urls.py apps/pages/test_rate_limits.py
git commit -m "feat: rate limit public account endpoints"
```

### Task 4: Make upload resource limits and quota atomic

**Files:**
- Create: `apps/pages/upload_services.py`
- Modify: `apps/pages/views.py:570-727`
- Create: `apps/pages/test_upload_limits.py`
- Modify: `apps/pages/tests.py`

**Interfaces:**
- Produces: `UploadResourceLimitError`; `UploadQuotaExceeded`; `PreparedJSONData(data, access_type, shared_users, size_bytes)`; `canonical_json_size(value) -> int`; `validate_upload_files(files) -> None`; `validate_json_depth(value) -> None`; `save_prepared_json_data(owner, objects) -> list[JSONData]`.

- [ ] **Step 1: Write failing boundary and rollback tests**

Cover 5/6 files, exactly/over 10 MiB, exactly/over 25 MiB combined, 100/101 objects, depth 100/101, rate-limit denial before parsing, compact Unicode size, 50 MiB quota rejection, quota freed by deletion, and a batch where resource rejection leaves `JSONData.objects.count() == 0`. Retain a regression test that one valid and one schema-invalid object saves exactly one record and reports the invalid object.

```python
@override_settings(PILOT_MAX_UPLOAD_OBJECTS=1)
def test_object_limit_rejects_entire_request_before_saving(self):
    response = self.client.post(reverse("upload_json"), {"file": self._json_file([self._valid("a"), self._valid("b")])})
    self.assertEqual(response.status_code, 200)
    self.assertEqual(JSONData.objects.count(), 0)
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_upload_limits -v 2`

Expected: FAIL because byte/depth/object/quota protections and stored sizes are absent.

- [ ] **Step 3: Implement focused upload helpers**

Use compact UTF-8 JSON size:

```python
def canonical_json_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
```

Check `UploadedFile.size` before calling `json.load`. Traverse parsed JSON iteratively with `(value, depth)` pairs and reject container depth above the setting. Reject non-finite floats. Count every unwrapped raw object before schema validation.

In `save_prepared_json_data`, open one `transaction.atomic()`, lock the owner row with `User.objects.select_for_update().get(pk=owner.pk)`, aggregate `Sum("size_bytes")`, reject when used plus incoming exceeds 50 MiB, and then create the whole prepared batch including sharing relations and notifications. Any exception rolls the complete batch back; do not add a drifting usage-counter table.

- [ ] **Step 4: Refactor the view into prepare-then-commit**

Consume the upload rate limit before reading files. Precheck all file byte limits, parse/unwrap and count resources, retain current `validate_json` partial schema behavior, collect valid objects in `PreparedJSONData`, and perform exactly one batch save after all resource checks pass. Fix the existing double `created_count += 1` so success counts match database rows.

- [ ] **Step 5: Run focused and full page tests**

Run: `python manage.py test apps.pages.test_upload_limits apps.pages.tests -v 2`

Expected: PASS; existing upload access-control behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/upload_services.py apps/pages/views.py apps/pages/test_upload_limits.py apps/pages/tests.py
git commit -m "feat: bound and quota pilot uploads"
```

### Task 5: Close legacy public mutation routes and add readiness

**Files:**
- Modify: `config/urls.py`
- Modify: `apps/pages/views.py`
- Modify: `apps/pages/urls.py`
- Create: `apps/pages/test_public_surface.py`

**Interfaces:**
- Produces: `/healthz/` named `healthz`, returning 200 only after `SELECT 1` succeeds.

- [ ] **Step 1: Write failing public-surface tests**

Assert `/api/product/`, legacy dynamic-table write/export/delete paths, generated `/api/`, and `/login/jwt/` do not resolve or return 404. Assert `/healthz/` returns JSON `{"status": "ok"}` and 200 with a live database, and 503 `{"status": "unavailable"}` when `connection.cursor()` raises `DatabaseError`.

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_public_surface -v 2`

Expected: FAIL because legacy routes are included and readiness is missing.

- [ ] **Step 3: Remove only URL exposure and add readiness**

Keep `apps.dyn_api` installed/importable but remove its URL include. Remove dynamic-table URL include and the broad try/except generated API/JWT block. Implement:

```python
def healthz_view(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
```

- [ ] **Step 4: Run focused and URL regression tests**

Run: `python manage.py test apps.pages.test_public_surface apps.pages.tests -v 2`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/urls.py apps/pages/views.py apps/pages/urls.py apps/pages/test_public_surface.py
git commit -m "security: close legacy public endpoints"
```

### Task 6: Make the Render Free blueprint reproducible

**Files:**
- Modify: `render.yaml`
- Modify: `build.sh`
- Test: `apps/pages/test_deployment_artifacts.py`

**Interfaces:**
- Consumes: `/healthz/`; production `DB_*` settings.
- Produces: Render service `fair-materials-data-hub`, `plan: free`, Python 3.12.13, one explicit Gunicorn worker.

- [ ] **Step 1: Write artifact behavior tests**

Parse `render.yaml` with `yaml.safe_load`, run `bash -n build.sh`, and execute a test copy of `build.sh` with a temporary fake `python` executable that records arguments. Assert install precedes collectstatic precedes migrate, and assert neither `makemigrations` nor Yarn is invoked.

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_deployment_artifacts -v 2`

Expected: FAIL because the current blueprint is paid, has four workers, and runs Yarn/makemigrations.

- [ ] **Step 3: Implement the free blueprint and build script**

Use `runtime: python`, `plan: free`, `region: frankfurt`, `buildCommand: bash build.sh`, `healthCheckPath: /healthz/`, and:

```yaml
startCommand: >-
  python -m gunicorn config.wsgi:application
  --bind 0.0.0.0:$PORT
  --workers 1
  --access-logfile -
  --error-logfile -
```

Declare `PYTHON_VERSION=3.12.13`, generated `SECRET_KEY`, exact public non-secret defaults, and `sync: false` for `DB_NAME`, `DB_USERNAME`, `DB_PASS`, `DB_HOST`, `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, and `ORCID_REDIRECT_URI`. Set `ORCID_BASE_URL=https://orcid.org`. Build script uses `set -euo pipefail`, installs requirements, collects static files, and migrates.

- [ ] **Step 4: Run artifact tests and production checks with dummy complete env**

Run: `python manage.py test apps.pages.test_deployment_artifacts -v 2 && bash -n build.sh`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add render.yaml build.sh apps/pages/test_deployment_artifacts.py
git commit -m "build: configure Render free pilot"
```

### Task 7: Run the complete pre-deploy gate

**Files:**
- Create: `docs/deployment/public-pilot.md`
- Modify only if a verification failure exposes a defect in a file changed above.

**Interfaces:**
- Consumes: all prior task outputs.

- [ ] **Step 1: Write the operator runbook**

Document the exact Supabase Session Pooler-to-Render environment mapping without real secrets, the final HTTPS ORCID callback including the trailing slash, creation of the first administrator from a controlled local command, free-tier sleep/pause/no-backup caveats, database export before ending the pilot, and this smoke sequence: register, password login, ORCID login, upload, search, share, export, redeploy, then confirm account/data persistence. State that the original uploaded files are not retained.

- [ ] **Step 2: Verify migration consistency**

Run: `python manage.py makemigrations --check --dry-run`

Expected: exit 0 and `No changes detected`.

- [ ] **Step 3: Run the full test suite**

Run: `python manage.py test -v 2`

Expected: all tests pass with no traceback or unexpected warning.

- [ ] **Step 4: Verify static collection**

Run: `python manage.py collectstatic --noinput`

Expected: exit 0.

- [ ] **Step 5: Verify production security settings without touching Supabase**

Run `python manage.py check --deploy` with `DEBUG=False`, a temporary strong `SECRET_KEY`, and complete dummy Postgres variables; the command only imports settings and must not print the password.

Expected: exit 0 with no Django security warning.

- [ ] **Step 6: Audit installed dependencies**

Run: `pip-audit --local`

Expected: no known vulnerabilities in direct runtime dependencies; investigate and fix any reported direct dependency before completion.
