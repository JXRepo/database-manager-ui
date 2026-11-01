# Password recovery

The login page currently shows an inert Forgot Password? label. Implement the
complete email recovery flow using the existing Django authentication system.

## Behavior

- Link both login URLs to an email form, a neutral request acknowledgement, a
  new password form, and a completion page with a Login link.
- Reuse Django's tokens and password validators. Tokens expire after one hour
  and become invalid after use or a change to the account's password or email.
- Require CSRF for submissions. Keep inactive accounts and accounts without a
  usable password ineligible. Do not automatically sign in after resetting.
- Existing sessions fail authentication after the password changes. Preserve
  ownership, data, profile details and ORCID connections.
- Unknown addresses get the same acknowledgement as eligible accounts. Limit
  requests by IP and destination address using the existing persisted limiter.
- Email remains optional. Explain the existing connected ORCID fallback for
  people who cannot use the saved address; do not recover an account by username
  alone or associate accounts by matching email addresses.
- Reuse the existing compact authentication card and English UI text.

## Delivery and configuration

Use a configurable Django mail backend. Provide Resend HTTPS delivery for the
current Render Free deployment, whose standard SMTP ports are blocked. Standard
SMTP remains available through environment settings for compatible hosting.
Do not add a dependency, create a provider account or send real test mail without
the required sender configuration and an explicitly supplied test recipient.

Production requires a configured sender, transport and canonical HTTPS site
origin. Derive the origin from Render's hostname unless explicitly configured.
Missing configuration produces a clear unavailable message, not a fake email
success. Provider failures must not expose email addresses, tokens or API keys.
Local development uses console email; tests use Django's isolated mail outbox.

The user has requested direct implementation. The provider account and sender
are still pending user input; implement and verify all independent code first.

## Approaches

- Selected: built in Django recovery with configured email delivery. This keeps
  the established account model and avoids custom token storage.
- A custom OTP system would add persistence and validation without a requested
  benefit. Ordinary SMTP alone does not fit the current Render Free deployment.

## Verification

Exercise the full reset and subsequent login, expired and reused links, CSRF,
password validation, eligibility, quotas, unavailable delivery and transport
failures. Check desktop Chromium with JavaScript enabled and disabled. Update
the user help and deployment instructions with the actual behavior.
