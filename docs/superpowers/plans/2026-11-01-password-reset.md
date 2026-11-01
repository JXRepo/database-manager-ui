# Password Recovery Implementation Plan

> **For agentic workers:** Use executing-plans to implement the tasks in order.

**Goal:** Make Forgot Password? a usable email password recovery flow.

**Architecture:** Keep Django's reset tokens and forms, with focused view and
mail modules. Use the existing database rate limiter and template style.

**Tech Stack:** Django 5.2, templates, requests, Chromium and Node.

**Spec:** ../specs/2026-11-01-password-reset-design.md

## Global Constraints

- One hour token lifetime; no automatic login or account merging.
- DEBUG=True and SQLite for local checks; resolve the local interpreter first.
- Preserve English UI and docstrings; docstring summaries have no final period.
- No new dependencies or production data changes. Keep secrets out of Git.
- Implement directly as requested; production sender configuration is pending.

## Review Focus

- A used, expired or mismatched token must not change a password.
- Unknown, disabled and ORCID-only accounts must not expose account existence.
- A hostile request host must not change the emailed production URL.
- Mail errors and missing settings must not leak credentials or claim delivery.
- Resetting a password must invalidate old sessions without touching owned data.

## Task 1: Recovery flow and mail delivery

Files: apps/pages/password_reset.py, apps/pages/email_backend.py,
config/settings.py, config/urls.py, templates/accounts/password_reset_*,
templates/accounts/login.html, apps/pages/test_password_reset.py,
apps/pages/test_public_surface.py and apps/pages/test_production_settings.py.

Interfaces: PasswordRecoveryView uses StyledPasswordResetForm and
password_reset_email_available(); PasswordRecoveryConfirmView uses
StyledSetPasswordForm; ResendEmailBackend implements send_messages(messages).

- [x] Write regression tests for the lifecycle and Review Focus cases.
- [x] Run the new URL tests and verify the current 404 failure.
- [x] Implement the four routes, forms, templates, mail backend and limits.
- [x] Run the recovery and related account tests; inspect every failure.

## Task 2: Help, deployment and browser verification

Files: README.md, env.sample, docs/deployment/public-pilot.md,
apps/pages/assistant_knowledge.py, related assistant fixtures and browser checks.

- [x] Update setup instructions and the assistant's outdated recovery answer.
- [x] Verify the full flow, errors and disabled JavaScript in desktop Chromium.
- [x] Run relevant Django tests and node --test tests/js/*.test.cjs.
- [x] Review the final diff, resolve material findings, then git add ., commit
  and push as requested by project instructions.
- [x] Verify deployed pages separately from push. Report sender configuration
  and actual delivery as pending until independently verified.

## Verification record

- The original lifecycle and login-link tests failed against the disabled routes
  before implementation, then passed with the recovery flow.
- The canonical-origin regression rejected an invalid port after the validation
  was corrected; a malformed origin cannot produce a reset email.
- 155 initial related Django tests passed, including native Chromium at 1280 pixels with
  JavaScript and 1920 pixels without it. Both browser cases followed the captured
  test email through password validation, completion and subsequent login.
- All 138 JavaScript tests passed with no skips. Screenshots showed readable
  request, validation and completion cards at the tested desktop widths.
- External email delivery remains pending sender configuration and an authorized
  real inbox test. Local tests do not establish real delivery.

## Final review

- An independent read-only review found two SMTP issues: production allowed
  plaintext and Django's default exception logging exposed server diagnostics.
  Both were reproduced by failing regression tests before the fixes.
- Production now requires an encrypted SMTP mode, and recovery uses generic
  transport-independent error logging while retaining Django's email rendering.
  Both regression tests passed after the fixes, and all 157 related Django tests
  passed, including the two full Chromium recovery cases and assistant browser
  regression checks. No JavaScript changed after the 138 passing Node tests.
- Deferred minor: synchronous sending can expose account eligibility through
  timing. Keep the persisted request limits and document this privacy limitation;
  durable background delivery is separate work, with no ad hoc threads or sleeps.
- Ruling: actual inbox delivery and Render rollout cannot be established by code
  review. Verify rollout separately and retain the explicit sender/test-inbox
  dependency. Local screenshots were independently inspected after browser tests.

## Published state

- Feature commit `ceb307a` was pushed to `origin/main`.
- Read-only checks on the public Render site confirmed the new recovery form
  returns 200, login links to it, malformed reset links show the intended error
  page, and `/healthz/` returns 200. These checks followed the actual rollout;
  the first checks still saw the previous version's 404.
- The live form explicitly reports unavailable recovery email. A verified sender
  and provider credentials are still required, followed by a real inbox test.
  No production mail was sent and no production account was changed.
