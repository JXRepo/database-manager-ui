from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import AccountProfile, RateLimitBucket
from .rate_limits import consume_rate_limit


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CredentialValidationTests(TestCase):
    """
    Check credential previews without creating or modifying accounts
    """

    path = "/accounts/validate-credentials/"

    def setUp(self):
        """
        Prepare synthetic credentials for an unregistered researcher
        """
        self.data = {
            "mode": "register",
            "username": "new_researcher",
            "email": "person@example.org",
            "password1": "Quartz!Mosaic72River",
            "password2": "Quartz!Mosaic72River",
        }

    def preview(self, **values):
        """
        Post synthetic credentials using the browser request format

        Parameters
        ----------
        **values : dict
            Overrides for the default credential fields.

        Returns
        -------
        HttpResponse
            Response from the credential preview endpoint.
        """
        return self.client.post(
            self.path,
            urlencode({**self.data, **values}),
            content_type="application/x-www-form-urlencoded",
        )

    def test_available_credentials_return_empty_field_errors(self):
        """
        Return the complete error contract for acceptable credentials
        """
        response = self.preview()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(reverse("validate_account_credentials"), self.path)
        self.assertEqual(response.json(), {"errors": {
            "username": [], "email": [], "password1": [], "password2": [],
        }})
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotContains(response, self.data["password1"])

    def test_taken_username_is_rejected_ignoring_case(self):
        """
        Catch both exact and differently capitalized duplicate names
        """
        User.objects.create_user(username="TakenName")

        for username in ("TakenName", "takenname", "TAKENNAME"):
            with self.subTest(username=username):
                response = self.preview(username=username)
                self.assertEqual(response.status_code, 200)
                self.assertIn("already exists", " ".join(response.json()["errors"]["username"]))

    def test_username_model_rules_are_previewed(self):
        """
        Reject missing names, spaces, unsupported punctuation, and long names
        """
        for username in ("", "two names", "researcher!", "x" * 151):
            with self.subTest(username=username):
                response = self.preview(username=username)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["errors"]["username"])

    def test_numeric_and_supported_unicode_usernames_are_allowed(self):
        """
        Keep valid numeric and Unicode names within Django's existing policy
        """
        for username in ("12345678", "研究者_Änne", "name.@+-_", "x" * 150):
            with self.subTest(username=username):
                response = self.preview(username=username)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["errors"]["username"], [])

    def test_password_policy_runs_before_confirmation_is_filled(self):
        """
        Report minimum length, common, numeric, and similar password failures
        """
        for password, message in (
            ("Ab3!x", "too short"),
            ("password", "too common"),
            ("987653216789", "entirely numeric"),
            ("new_researcher!", "too similar"),
        ):
            with self.subTest(message=message):
                response = self.preview(password1=password, password2="")
                self.assertEqual(response.status_code, 200)
                errors = response.json()["errors"]
                self.assertIn(message, " ".join(errors["password1"]))
                self.assertEqual(errors["password2"], ["This field is required."])

    def test_password_checks_and_confirmation_mismatch_are_separate(self):
        """
        Show both a weak first password and a different confirmation
        """
        response = self.preview(password1="123", password2="not-the-same")

        self.assertEqual(response.status_code, 200)
        errors = response.json()["errors"]
        self.assertIn("too short", " ".join(errors["password1"]))
        self.assertIn("didn", " ".join(errors["password2"]))
        self.assertNotIn("too short", " ".join(errors["password2"]))

    def test_confirmed_weak_password_errors_belong_to_first_password(self):
        """
        Avoid placing password strength failures beside matching confirmation
        """
        response = self.preview(password1="password", password2="password")

        self.assertEqual(response.status_code, 200)
        errors = response.json()["errors"]
        self.assertIn("too common", " ".join(errors["password1"]))
        self.assertEqual(errors["password2"], [])

    def test_missing_passwords_are_reported(self):
        """
        Keep required field errors distinct for the two password inputs
        """
        response = self.preview(password1="", password2="")

        self.assertEqual(response.status_code, 200)
        errors = response.json()["errors"]
        self.assertEqual(errors["password1"], ["This field is required."])
        self.assertEqual(errors["password2"], ["This field is required."])

    def test_special_characters_are_allowed_in_passwords(self):
        """
        Accept a strong password containing punctuation without extra policy
        """
        password = "Quartz<>!Mosaic72&River"
        response = self.preview(password1=password, password2=password)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["errors"]["password1"], [])
        self.assertEqual(response.json()["errors"]["password2"], [])

    def test_registration_email_is_validated_and_used_for_similarity(self):
        """
        Include the optional email in the same validation used during signup
        """
        response = self.preview(email="invalid-address")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["errors"]["email"])

        response = self.preview(
            email="DistinctiveResearcher@example.org",
            password1="DistinctiveResearcher!",
            password2="",
        )
        self.assertIn("too similar", " ".join(response.json()["errors"]["password1"]))

    def test_preview_creates_no_accounts_profiles_or_login(self):
        """
        Keep successful previews free of persistent account or session changes
        """
        response = self.preview()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(AccountProfile.objects.count(), 0)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_registration_does_not_exclude_the_authenticated_username(self):
        """
        Reserve the current name when previewing a separate registration
        """
        user = User.objects.create_user(username="current_user", password="fixture")
        self.client.force_login(user)

        response = self.preview(username=user.username)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["errors"]["username"])

    def test_get_is_not_allowed(self):
        """
        Prevent credentials from being submitted in a GET request
        """
        response = self.client.get(self.path)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(RateLimitBucket.objects.exists())

    def test_unknown_mode_is_rejected(self):
        """
        Reject request modes outside the two account creation flows
        """
        response = self.preview(mode="settings")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_csrf_token_is_required(self):
        """
        Protect password previews with Django's CSRF validation
        """
        protected_client = Client(enforce_csrf_checks=True)
        response = protected_client.post(self.path, self.data)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(RateLimitBucket.objects.exists())

    def test_valid_csrf_token_allows_preview(self):
        """
        Allow a preview carrying the token issued on the registration page
        """
        protected_client = Client(enforce_csrf_checks=True)
        protected_client.get(reverse("register"))
        token = protected_client.cookies["csrftoken"].value
        response = protected_client.post(
            self.path, self.data, HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)

    @override_settings(PILOT_RATE_LIMITS={
        "credential_validation": {"limit": 2, "window_seconds": 60},
        "registration": {"limit": 1, "window_seconds": 60},
    })
    def test_preview_limit_is_independent_per_ip_and_returns_retry_after(self):
        """
        Bound checks independently from registration without blocking other IPs
        """
        now = datetime(2026, 9, 16, 12, 0, 30, tzinfo=timezone.utc)
        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            consume_rate_limit("registration", "127.0.0.1")
            self.assertEqual(self.preview().status_code, 200)
            self.assertEqual(self.preview().status_code, 200)
            response = self.preview()
            other_ip_response = self.client.post(
                self.path, self.data, REMOTE_ADDR="192.0.2.10",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "30")
        self.assertIn("error", response.json())
        self.assertEqual(other_ip_response.status_code, 200)
        self.assertEqual(RateLimitBucket.objects.get(scope="registration").count, 1)

    def test_rate_limit_database_failure_fails_closed(self):
        """
        Return an unavailable response when the abuse guard cannot persist
        """
        with patch.object(
            RateLimitBucket.objects, "get_or_create", side_effect=DatabaseError,
        ):
            response = self.preview()

        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())
        self.assertFalse(User.objects.exists())

    def test_oversized_fields_skip_preview_without_setting_password_policy(self):
        """
        Bound preview work without claiming long credentials are invalid
        """
        response = self.preview(password1="x" * 4097)

        self.assertEqual(response.status_code, 413)
        self.assertIn("submit", response.json()["error"].lower())
        self.assertNotIn("errors", response.json())

    def test_oversized_request_body_is_rejected(self):
        """
        Refuse large preview requests before spending effort on form validation
        """
        response = self.preview(extra="x" * 40000)

        self.assertEqual(response.status_code, 413)
        self.assertIn("error", response.json())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ORCIDCredentialValidationTests(TestCase):
    """
    Check previews against only the authenticated pending ORCID account
    """

    path = "/accounts/validate-credentials/"

    def setUp(self):
        """
        Create a pending ORCID account and its authenticated preview client
        """
        self.user = User.objects.create_user(
            username="orcid_researcher", email="DistinctiveResearcher@example.org",
        )
        self.profile = AccountProfile.objects.create(
            user=self.user, authenticated_orcid="0000-0002-1451-2715",
        )
        self.data = {
            "mode": "orcid_setup", "username": "new_researcher",
            "password1": "Quartz!Mosaic72River", "password2": "Quartz!Mosaic72River",
        }
        self.client.force_login(self.user)

    def test_pending_account_can_preview_without_mutating_account(self):
        """
        Pass through the setup gate while preserving user, profile, and session
        """
        # initialize the login policy before the page starts credential previews
        self.assertEqual(self.client.get(reverse("orcid_setup_credentials")).status_code, 200)
        user_before = User.objects.values().get(pk=self.user.pk)
        profile_before = AccountProfile.objects.values().get(pk=self.profile.pk)
        session_before = dict(self.client.session)

        response = self.client.post(self.path, self.data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["errors"]["username"], [])
        self.assertEqual(User.objects.values().get(pk=self.user.pk), user_before)
        self.assertEqual(AccountProfile.objects.values().get(pk=self.profile.pk), profile_before)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(AccountProfile.objects.count(), 1)
        self.assertEqual(dict(self.client.session), session_before)

    def test_current_username_is_available_with_different_case(self):
        """
        Exclude only the current user when checking an ORCID setup name
        """
        response = self.client.post(self.path, {
            **self.data, "username": "ORCID_RESEARCHER",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["errors"]["username"], [])

    def test_another_username_cannot_be_excluded_using_posted_user_id(self):
        """
        Ignore attacker supplied account identifiers when checking uniqueness
        """
        other_user = User.objects.create_user(username="TakenName")
        response = self.client.post(self.path, {
            **self.data, "username": "takenname", "user_id": other_user.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["errors"]["username"])

    def test_username_and_password_policies_match_orcid_setup(self):
        """
        Reject surrounding username whitespace and weak unconfirmed passwords
        """
        response = self.client.post(self.path, {
            **self.data, "username": " leading", "password1": "123", "password2": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["errors"]["username"])
        self.assertIn("too short", " ".join(response.json()["errors"]["password1"]))

    def test_similarity_uses_existing_email_not_posted_email(self):
        """
        Keep password similarity aligned with the unchanged ORCID account email
        """
        response = self.client.post(self.path, {
            **self.data, "email": "different@example.org",
            "password1": "DistinctiveResearcher!", "password2": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("too similar", " ".join(response.json()["errors"]["password1"]))

    def test_anonymous_orcid_preview_is_forbidden(self):
        """
        Require an authenticated account before excluding any existing username
        """
        self.client.logout()
        response = self.client.post(self.path, self.data)

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_account_with_usable_password_cannot_use_orcid_preview(self):
        """
        Limit the ORCID mode to accounts still awaiting initial credentials
        """
        self.user.set_password("fixture")
        self.user.save(update_fields=["password"])
        self.client.force_login(self.user)

        response = self.client.post(self.path, self.data)

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_unverified_account_cannot_use_orcid_preview(self):
        """
        Require a verified ORCID identity rather than an unusable password alone
        """
        self.profile.authenticated_orcid = None
        self.profile.save(update_fields=["authenticated_orcid"])

        response = self.client.post(self.path, self.data)

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())
