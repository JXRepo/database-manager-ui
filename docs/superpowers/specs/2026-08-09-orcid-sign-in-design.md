# ORCID Sign-In Design

## Purpose

Allow an anonymous user to sign in with ORCID. The first successful ORCID
authorization creates a normal local Django account automatically; later
authorizations sign the user into that same account. Existing
username/password registration and login remain available.

The implementation uses the ORCID Public API `/authenticate` scope and the
existing server-side authorization-code exchange. It does not store the ORCID
access token because the application does not need to call ORCID APIs after
authentication.

## Selected Approach

Add a dedicated verified ORCID identity to `AccountProfile` and keep the
current custom OAuth code small and explicit.

This is preferred over a generic external-identity table because ORCID is the
only external identity provider in scope. It is preferred over adding a social
authentication framework because that would increase dependencies and replace
working local authentication immediately before deployment.

## Identity Model

`AccountProfile` gains:

- `authenticated_orcid`: nullable, unique, non-editable, canonical 19-character
  ORCID iD;
- `orcid_authenticated_at`: nullable timestamp of the latest successful link or
  initial identity creation.

The existing `orcid` field is legacy, unverified data. A migration preserves it
but never copies it into `authenticated_orcid`. Existing users must complete
ORCID authorization before their ORCID can be used for authentication.

The account settings form no longer accepts a manually entered ORCID. The page
shows a verified ORCID separately and offers an explicit Connect ORCID action.
Neither form posts nor administrator-supplied display values can create an
authenticated identity without OAuth.

## OAuth Transaction

The login start route is publicly accessible at `/login/orcid/`. The existing
account-link start route remains login-protected. Both routes store one
short-lived transaction in the Django session:

```text
state
intent: login or link
initiating user id for link
created timestamp
validated local next path
```

The callback consumes the transaction before any other processing. It then:

1. validates the transaction structure and a ten-minute expiry;
2. compares the returned state with constant-time comparison;
3. rejects unknown intent values;
4. handles provider cancellation without exchanging a code;
5. exchanges a valid authorization code over HTTPS;
6. requires a token payload containing an access token and an ORCID iD;
7. normalizes and validates the ORCID format and ISO 7064 MOD 11-2 checksum;
8. executes the login or link intent.

Only same-host `next` paths are retained. External URLs, scheme-relative URLs,
and HTTPS downgrades are discarded. A consumed, expired, or mismatched state
cannot be replayed.

## First Sign-In and Returning Sign-In

For a login intent:

- If `authenticated_orcid` belongs to an active user, Django logs in that user.
- If it belongs to an inactive user, login is refused and no replacement
  account is created.
- If it is not yet linked, one transaction atomically creates a standard active
  user and profile, stores the verified ORCID, and logs in the new user.

The generated username is derived from the ORCID digits and has a safe suffix
only if the preferred username is occupied. A matching username, display name,
email address, or legacy hand-entered ORCID never causes account linking. The
new user has an unusable password, an empty email address, and no staff or
superuser privileges. The user can later choose a normal username in account
settings.

A database uniqueness constraint is the final protection against two accounts
claiming one authenticated ORCID. If simultaneous first callbacks race, the
losing transaction does not leave an orphan user and instead signs in the one
identity created by the successful transaction.

If a legacy hand-entered ORCID matches the authenticated ORCID returned during
anonymous login, automatic account creation is blocked. The user is told to
sign in with the existing local account and use Connect ORCID. This avoids both
account takeover and accidental duplicate accounts.

## Account Linking

For a link intent:

- the browser must still be authenticated as the initiating user;
- linking the same verified ORCID again is idempotent;
- a user who already has a different verified ORCID cannot silently replace it;
- an ORCID already linked to another account is rejected without changing
  either account;
- logout or session switching between start and callback invalidates the link.

Account merging and ORCID transfer are not automatic. A future administrative
recovery process can handle genuine conflicts after independent identity
verification.

## Callback Errors and Privacy

Cancellation, missing parameters, expired state, provider HTTP errors, network
timeouts, invalid JSON, invalid token payloads, and invalid ORCID checksums all
return concise user-facing messages. Responses and logs never include the
authorization code, access token, client secret, database password, or provider
error description.

Login failures do not reveal whether an ORCID belongs to an inactive account or
another local account beyond the action needed by the legitimate user.

## User Interface

- The login page keeps the username/password form and adds a visually separate
  `Sign in with ORCID` action.
- The registration page remains available for public local registration.
- Account settings removes the editable ORCID input and labels an authenticated
  ORCID as verified.
- Provider cancellation returns to the login or account settings page according
  to the original intent.
- Successful login returns to a validated local `next` target or `/search/`.

The exact production redirect URI remains one callback path and is entered in
both ORCID Developer Tools and Render:

```text
https://<actual-render-host>/settings/orcid/callback/
```

The trailing slash is required and the value must match exactly.

## Security Settings

- Production cookies are secure and use `SameSite=Lax`, which permits the
  top-level OAuth return request to include the session cookie.
- The redirect URI is explicitly configured and uses HTTPS.
- The ORCID client secret exists only in Render environment variables.
- The application never trusts ORCID values submitted through HTML forms.
- The callback accepts only a session transaction created by this application.
- ORCID login start is rate-limited as part of the open-registration pilot.

## Test Strategy

Tests are written before implementation and cover:

- unique nullable verified identities and preservation of legacy values;
- valid ORCID checksums, including `X`, and rejection of malformed identifiers;
- login and link authorization URLs without secret leakage;
- safe and unsafe `next` values;
- state mismatch, absence, expiry, intent tampering, and replay;
- provider cancellation before code exchange;
- HTTP, URL, timeout, JSON, and token-payload failures;
- existing active and inactive identities;
- atomic first-user creation and repeat login;
- username collisions without account takeover;
- concurrent identity uniqueness conflict without orphan users;
- legacy ORCID collision blocking;
- link identity and session-user conflicts;
- inability to forge authenticated ORCID through account-settings posts;
- login template action and unchanged local password login;
- absence of secrets in messages and responses.

The focused ORCID tests run during each red-green cycle. The entire Django test
suite, migration drift check, and production deployment checks run before the
feature is considered ready.

## Non-Goals

- reading or modifying an ORCID record after login;
- retaining, refreshing, encrypting, or revoking ORCID access tokens;
- automatic account merging based on email, name, username, or legacy ORCID;
- supporting Google, Microsoft, or other external identity providers;
- custom ORCID member API scopes.
