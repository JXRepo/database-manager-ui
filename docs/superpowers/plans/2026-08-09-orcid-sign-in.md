# Verified ORCID Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anonymous users sign in with a verified ORCID iD, automatically create a safe local account on first use, and let existing local users explicitly link one verified ORCID identity.

**Architecture:** A dedicated nullable unique field stores only identities returned by ORCID OAuth; the existing hand-entered field remains legacy and untrusted. Login and link share one callback and a single-use, expiring session transaction that records intent. The callback validates provider output, resolves conflicts atomically, never stores the access token, and never associates accounts by name, email, legacy ORCID, or generated username.

**Tech Stack:** Django 5.2, Django sessions/auth, PostgreSQL unique constraints, ORCID OAuth `/authenticate`, Python standard-library HTTP client.

## Global Constraints

- Use ORCID production base URL `https://orcid.org` in Render; tests use the sandbox URL.
- The exact callback is `/settings/orcid/callback/` with its trailing slash; `ORCID_REDIRECT_URI` and the ORCID developer console must match the final HTTPS URL character-for-character.
- Never commit, log, display, or persist `ORCID_CLIENT_SECRET`, authorization codes, or access tokens.
- Only `AccountProfile.authenticated_orcid` is a login identity. Existing `AccountProfile.orcid` remains unverified legacy data and is never copied or queried to authenticate a user.
- `authenticated_orcid` is nullable, unique, non-editable, canonical 19-character ORCID format; migration is `apps/pages/migrations/0008_accountprofile_authenticated_orcid.py`.
- A first ORCID login creates an active ordinary user with empty email, unusable password, `is_staff=False`, and `is_superuser=False`.
- Never associate by provider name/email, local email, username, or legacy ORCID; a legacy matching claim blocks first-account creation and instructs local login plus Connect.
- One session transaction contains `state`, `intent`, `user_id`, `created_at`, and safe local `next`; it is consumed once and expires after 600 seconds.
- `state` uses `secrets.token_urlsafe(24)` and `secrets.compare_digest`.
- `/login/orcid/` consumes `consume_rate_limit("orcid_start", get_client_identifier(request))`; denial returns 429 with `Retry-After` and creates no OAuth transaction.
- Production session cookies remain Secure and SameSite Lax so the top-level ORCID callback carries the session.
- All comments and docstrings are English; a docstring's first line must not end in a period.

---

### Task 1: Separate verified ORCID identity from legacy profile text

**Files:**
- Modify: `apps/pages/models.py:69-89`
- Create: `apps/pages/migrations/0008_accountprofile_authenticated_orcid.py`
- Modify: `apps/pages/forms.py:86-165`
- Modify: `apps/pages/views.py:103-127`
- Modify: `templates/accounts/settings.html:145-215`
- Create: `apps/pages/test_orcid_identity.py`

**Interfaces:**
- Produces: `AccountProfile.authenticated_orcid: str | None`; `AccountProfile.orcid_authenticated_at: datetime | None`.

- [ ] **Step 1: Write failing identity-boundary tests**

Assert multiple null identities are allowed, duplicate non-null identities violate the database constraint, migration leaves an existing legacy `orcid` unverified, and forged POST keys cannot change either verified field or the legacy field.

```python
def test_settings_post_cannot_create_verified_identity(self):
    self.client.force_login(self.user)
    self.client.post(reverse("account_settings"), {
        "username": self.user.username,
        "email": "",
        "institution": "ICAMS",
        "orcid": "0000-0002-1451-2715",
        "authenticated_orcid": "0000-0002-1451-2715",
    })
    profile = AccountProfile.objects.get(user=self.user)
    self.assertEqual(profile.orcid, "")
    self.assertIsNone(profile.authenticated_orcid)
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_orcid_identity -v 2`

Expected: FAIL because the verified fields and security boundary do not exist.

- [ ] **Step 3: Add fields without trusting old data**

Add:

```python
authenticated_orcid = models.CharField(
    max_length=19,
    null=True,
    blank=True,
    unique=True,
    editable=False,
)
orcid_authenticated_at = models.DateTimeField(
    null=True,
    blank=True,
    editable=False,
)
```

Migration `0008` depends on `0007` and only adds the two fields; it has no data-copy operation.

- [ ] **Step 4: Remove hand-entry and display verified status**

Remove `orcid` from `AccountSettingsForm`, its initializer/cleaner, and profile save code. Keep institution editing. In the settings template show `profile.authenticated_orcid|default:"Not connected"` and label it `Verified ORCID iD`; do not display legacy `profile.orcid` as authenticated.

- [ ] **Step 5: Run focused and existing account tests**

Run: `python manage.py test apps.pages.test_orcid_identity apps.pages.tests -v 2`

Expected: PASS after updating the old hand-entry test to assert the posted ORCID is ignored.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/models.py apps/pages/migrations/0008_accountprofile_authenticated_orcid.py apps/pages/forms.py apps/pages/views.py templates/accounts/settings.html apps/pages/test_orcid_identity.py apps/pages/tests.py
git commit -m "feat: separate verified ORCID identities"
```

### Task 2: Validate ORCID identifiers and single-use OAuth transactions

**Files:**
- Create: `apps/pages/orcid_auth.py`
- Create: `apps/pages/test_orcid_auth.py`

**Interfaces:**
- Produces: `ORCID_TRANSACTION_SESSION_KEY`; `ORCIDTransaction`; `normalize_orcid(value) -> str`; `start_orcid_transaction(request, intent, user_id=None, next_url="") -> str`; `consume_orcid_transaction(request, received_state) -> ORCIDTransaction`; `ORCIDFlowError`.

- [ ] **Step 1: Write failing pure and session tests**

Use hand-checked ORCID literals. Accept numeric-checksum `0000-0002-1451-2715` and X-checksum `0000-0002-1694-233X`; reject URLs, missing hyphens, lowercase `x`, whitespace-polluted strings, wrong checksum, and empty values. Test state mismatch, replay, malformed session data, unknown intent, and age exactly/over 600 seconds. Test local `/search/` next is retained while `https://evil.example/`, `//evil.example/`, and production HTTP downgrade are discarded.

```python
def test_wrong_checksum_is_rejected(self):
    with self.assertRaises(ORCIDFlowError):
        normalize_orcid("0000-0002-1451-2716")

def test_callback_transaction_is_consumed_once(self):
    state = start_orcid_transaction(self.request, "login")
    consume_orcid_transaction(self.request, state)
    with self.assertRaises(ORCIDFlowError):
        consume_orcid_transaction(self.request, state)
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_orcid_auth.ORCIDValidationTests apps.pages.test_orcid_auth.ORCIDTransactionTests -v 2`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement checksum validation**

Require `re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", value)`. Remove hyphens, calculate the ISO 7064 MOD 11-2 digit from the first 15 digits, map value 10 to `X`, and require an exact match with the returned check character. Do not accept an ORCID URL or silently strip attacker-controlled decoration.

- [ ] **Step 4: Implement safe session transactions**

Use a frozen dataclass with `state`, `intent`, `user_id`, `created_at`, and `next_url`. Start replaces any previous transaction. Consume must `pop` before validation, require `intent in {"login", "link"}`, use `secrets.compare_digest`, and reject older than 600 seconds. Sanitize `next` with `url_has_allowed_host_and_scheme` and `require_https=not settings.DEBUG`; default to `/search/`.

- [ ] **Step 5: Run focused tests**

Run: `python manage.py test apps.pages.test_orcid_auth.ORCIDValidationTests apps.pages.test_orcid_auth.ORCIDTransactionTests -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/orcid_auth.py apps/pages/test_orcid_auth.py
git commit -m "feat: validate ORCID OAuth transactions"
```

### Task 3: Start anonymous login and authenticated linking safely

**Files:**
- Modify: `apps/pages/views.py:133-211`
- Modify: `apps/pages/urls.py:35-43`
- Modify: `templates/accounts/login.html`
- Modify: `templates/accounts/settings.html`
- Modify: `apps/pages/test_orcid_auth.py`

**Interfaces:**
- Consumes: `start_orcid_transaction`; `consume_rate_limit("orcid_start", get_client_identifier(request))`.
- Produces: route `orcid_login` at `/login/orcid/`; existing route `orcid_connect`; shared authorization URL with `/authenticate` scope.

- [ ] **Step 1: Write failing start-flow tests**

Test anonymous login start and authenticated link start store different intents; link records current user id; authorize URL includes exact client id, callback, state, response type, and encoded `/authenticate`, but not client secret. Missing credentials creates no transaction. A second start invalidates the first. Rate-limit denial returns 429 with `Retry-After`, does not redirect to ORCID, and leaves no session transaction.

```python
@override_settings(ORCID_CLIENT_ID="APP-TEST", ORCID_CLIENT_SECRET="secret")
def test_anonymous_login_start_records_login_intent(self):
    response = self.client.get(reverse("orcid_login"))
    self.assertEqual(response.status_code, 302)
    transaction = self.client.session[ORCID_TRANSACTION_SESSION_KEY]
    self.assertEqual(transaction["intent"], "login")
    self.assertIsNone(transaction["user_id"])
    self.assertNotIn("secret", response["Location"])
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python manage.py test apps.pages.test_orcid_auth.ORCIDStartTests -v 2`

Expected: FAIL because anonymous ORCID login and intent transactions are absent.

- [ ] **Step 3: Implement one shared start helper**

Before creating state, require both credentials and consume the database-backed limit for the client identifier. Use `start_orcid_transaction(request, intent, user_id, request.GET.get("next", ""))`, then redirect to the existing ORCID authorize endpoint. Keep `orcid_connect_view` protected by `@login_required`; leave `orcid_login_view` anonymous.

- [ ] **Step 4: Add route and minimal login button**

Add `path("login/orcid/", views.orcid_login_view, name="orcid_login")`. On the login form, add a normal anchor whose URL is `{% url 'orcid_login' %}` and append the already-sanitized local `next` value through Django template URL encoding. Label it `Sign in with ORCID`. Keep username/password login and registration unchanged.

- [ ] **Step 5: Run start and template tests**

Run: `python manage.py test apps.pages.test_orcid_auth.ORCIDStartTests apps.pages.tests -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/views.py apps/pages/urls.py templates/accounts/login.html templates/accounts/settings.html apps/pages/test_orcid_auth.py
git commit -m "feat: start ORCID login and linking"
```

### Task 4: Complete verified login and first-account creation

**Files:**
- Modify: `apps/pages/orcid_auth.py`
- Modify: `apps/pages/views.py:212-253`
- Modify: `apps/pages/test_orcid_auth.py`

**Interfaces:**
- Produces: `complete_orcid_login(request, orcid, next_url) -> HttpResponse`; callback accepts anonymous users and routes by transaction intent.

- [ ] **Step 1: Write failing login callback tests**

Mock only `_exchange_orcid_authorization_code`; keep sessions, auth, database, account creation, and redirects real. Provider fixtures must include `access_token`, `orcid`, `name`, and `token_type`. Cover existing active identity login, inactive rejection, first login creation, repeat login reuse, derived username collision, legacy-claim block, same email/name non-association, unique identity race without orphan user, safe next redirect, and already-authenticated same/different identity behavior.

```python
def test_first_verified_login_creates_passwordless_ordinary_user(self):
    response = self._complete_login({
        "access_token": "provider-token",
        "orcid": "0000-0002-1451-2715",
        "name": "Researcher",
        "token_type": "bearer",
    })
    user = AccountProfile.objects.get(authenticated_orcid="0000-0002-1451-2715").user
    self.assertFalse(user.has_usable_password())
    self.assertEqual(user.email, "")
    self.assertFalse(user.is_staff)
    self.assertFalse(user.is_superuser)
    self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
```

- [ ] **Step 2: Write failing callback error tests**

Cover missing transaction/state/code, mismatch, replay, expiry, access denial, HTTPError, URLError, timeout, invalid JSON, non-dict payload, missing token, missing ORCID, invalid/checksum ORCID, and tampered intent. Assert no user/profile mutation and that responses/messages never contain code, token, secret, or provider `error_description`.

- [ ] **Step 3: Run the focused callback tests and record RED**

Run: `python manage.py test apps.pages.test_orcid_auth.ORCIDLoginCallbackTests apps.pages.test_orcid_auth.ORCIDCallbackFailureTests -v 2`

Expected: FAIL because callback is login-required and writes the legacy field.

- [ ] **Step 4: Implement login identity resolution atomically**

Remove `@login_required` from callback. Consume transaction before exchanging code. Require a dict payload with non-empty `access_token` and validated canonical `orcid`; do not store the token.

For `intent="login"`, look up only `authenticated_orcid`. Reject inactive users. If no verified identity exists, block when any legacy `orcid` exactly matches. Otherwise, in `transaction.atomic()`, derive a username such as `orcid_0000000214512715` from the 16 ORCID digits (append a safe numeric suffix on collision), call `set_unusable_password()`, save the ordinary user, and create its verified profile with `orcid_authenticated_at=timezone.now()`. Catch an identity uniqueness race outside the rolled-back transaction and fetch the winner; never leave an orphan user.

If the browser is already logged in, return success only when its verified identity is the same; never switch to a different account. Redirect only to the transaction's sanitized `next_url`.

- [ ] **Step 5: Implement safe error handling and run tests**

Catch `HTTPError`, `URLError`, `TimeoutError`, `json.JSONDecodeError`, `UnicodeDecodeError`, and malformed payload types. Use fixed local messages. Do not echo provider response fields. Run:

`python manage.py test apps.pages.test_orcid_auth.ORCIDLoginCallbackTests apps.pages.test_orcid_auth.ORCIDCallbackFailureTests -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/orcid_auth.py apps/pages/views.py apps/pages/test_orcid_auth.py
git commit -m "feat: sign in and create accounts with ORCID"
```

### Task 5: Complete explicit verified linking and regression gate

**Files:**
- Modify: `apps/pages/orcid_auth.py`
- Modify: `apps/pages/views.py`
- Modify: `apps/pages/test_orcid_auth.py`
- Modify: `apps/pages/tests.py`

**Interfaces:**
- Produces: `complete_orcid_link(request, transaction, orcid) -> HttpResponse` that never overwrites or transfers identities.

- [ ] **Step 1: Write failing linking conflict tests**

Cover initiating user differs from callback session, logged-out callback, ORCID already belongs to another user, current user links same iD twice, current user attempts to replace a different verified iD, and login/link state intent cannot be interchanged. Every rejection leaves both profiles unchanged.

```python
def test_link_cannot_take_identity_from_another_user(self):
    AccountProfile.objects.create(user=self.other, authenticated_orcid="0000-0002-1451-2715")
    response = self._complete_link(self.user, "0000-0002-1451-2715")
    self.assertRedirects(response, reverse("account_settings"))
    self.assertIsNone(AccountProfile.objects.get(user=self.user).authenticated_orcid)
    self.assertEqual(AccountProfile.objects.get(user=self.other).authenticated_orcid, "0000-0002-1451-2715")
```

- [ ] **Step 2: Run link tests and record RED**

Run: `python manage.py test apps.pages.test_orcid_auth.ORCIDLinkCallbackTests -v 2`

Expected: FAIL because explicit verified conflict handling is missing.

- [ ] **Step 3: Implement linking under the unique constraint**

Require an authenticated request and `transaction.user_id == request.user.pk`. Inside `transaction.atomic()`, lock/create the current profile, accept the same verified ORCID idempotently, reject replacement of a different verified ORCID, and reject one owned by another user. On first valid link set both verified fields. Never mutate the legacy `orcid` field.

- [ ] **Step 4: Run all ORCID, account, and migration tests**

Run: `python manage.py test apps.pages.test_orcid_auth apps.pages.test_orcid_identity apps.pages.tests -v 2 && python manage.py makemigrations --check --dry-run`

Expected: all tests PASS and `No changes detected`.

- [ ] **Step 5: Run the full project gate**

Run: `python manage.py test -v 2 && python manage.py check`

Expected: all tests pass and system check reports no issue.

- [ ] **Step 6: Commit**

```bash
git add apps/pages/orcid_auth.py apps/pages/views.py apps/pages/test_orcid_auth.py apps/pages/tests.py
git commit -m "feat: link verified ORCID identities safely"
```
