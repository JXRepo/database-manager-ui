# Upload continuity implementation plan

> **For agentic workers:** Use subagent-driven-development to implement the independent tasks below

**Goal:** Explain all upload limits and preserve observable uploads during internal navigation.

**Architecture:** Keep legacy form and NDJSON uploads. Add private durable task
records, ephemeral file staging and a supervised worker. Keep the browser document
alive during transfer using full application pages in a temporary frame.

**Tech Stack:** Django, PostgreSQL or local SQLite, Gunicorn, browser XHR, existing Bootstrap.

**Spec:** docs/superpowers/specs/2026-09-23-upload-continuity-design.md

## Global constraints

- English UI and comments; first docstring line has no trailing period.
- No new paid services, raw-file database storage or automatic upload retries.
- Preserve permissions, all batch prechecks and file atomicity.
- No production database access for development or tests.
- Desktop browser verification; commit and push only reviewed changes.

## Tasks

- [x] Limits: a settings-backed template tag and compact upload-page explanation;
  test changed settings render correctly and existing limits remain enforced.
- [x] Processing hooks: optional `progress(stage, completed, total)` and
  `on_saved(file_report)` in `_process_upload_file`; invoke completion inside the
  save transaction. Test all objects including invalid ones and rollback when
  recording the result fails. Preserve old callers without callbacks.
- [x] Jobs: add owner-scoped `/upload/jobs/` POST/GET and UUID detail GET; stage
  one multipart batch privately; return `{job: snapshot}`. Snapshot has id,
  status, files, summary, level, report_html and timestamps. File snapshots have
  name, status, validated_count, object_count and saved_count.
- [x] Worker: bind jobs to a shared process-instance UUID; validate all files
  before saving; publish real progress and atomic outcomes; expire interrupted
  work without retry. Test authorization, prechecks, result commits and cleanup.
- [x] Navigation: temporary full-page frame with a compact status bar, narrowly
  allow same-origin embedding for authenticated application views. Test auth
  pages still deny framing and child views keep their ordinary scripts.
- [x] Browser: real XHR byte progress and owner-scoped status recovery, elapsed
  time, explicit interrupted states, retained confirmed file results. Keep the
  ordinary form fallback. Test navigation during transfer and processing.
- [x] Deployment and docs: start worker with the existing web service, supervise
  both processes, retain privacy-safe access logging; document ephemeral staging
  and local worker startup. Test the launch contract.
- [x] Run focused Django and browser regression suites, inspect desktop layouts,
  request independent review and inspect the diff.

## Validation completed

- 652 Django tests passed on isolated local SQLite; 98 JavaScript tests passed
  with Chromium and no skipped cases.
- Real Gunicorn and worker startup, shutdown and restart were exercised with an
  isolated SQLite database and private temporary staging. One hundred synthetic
  objects were saved, repeated submission identities reused the same task, and
  a new submission of duplicate data saved nothing and retained detailed errors.
- Real throttled browser transfer survived Search, My Data and Upload navigation;
  only one POST was sent. Fresh pages recovered the owned result. Desktop checks
  at 1280 and 1440 pixels included empty selection and long file names.
- Migration drift check passed; migration 0013 was applied to local SQLite.
- Independent reviews covered result atomicity, permissions, staging cleanup,
  worker expiry and lock ordering, browser history and authentication changes.
  Production PostgreSQL concurrency and the live Render deployment were not tested.

Delivery follows the repository's authorized commit and push workflow. A successful
push does not establish that Render has finished deploying.
