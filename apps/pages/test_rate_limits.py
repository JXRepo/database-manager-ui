import hashlib
import hmac
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.db import DatabaseError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from .models import RateLimitBucket
from .rate_limits import (
    check_rate_limit,
    consume_rate_limit,
    get_client_identifier,
    reset_rate_limit,
)


class RateLimitServiceTests(TestCase):
    """
    Test persistent fixed window rate limit behavior
    """

    def setUp(self):
        """
        Create request helpers used by the service tests
        """
        self.factory = RequestFactory()

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 60}}
    )
    def test_consume_rejects_after_literal_limit_without_incrementing_denial(self):
        """
        Reject consumption after one action and leave the count unchanged
        """
        now = datetime(2026, 8, 9, 12, 0, 30, tzinfo=datetime_timezone.utc)

        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            first = consume_rate_limit("registration", "192.0.2.10")
            denied = consume_rate_limit("registration", "192.0.2.10")

        self.assertTrue(first.allowed)
        self.assertEqual(first.retry_after_seconds, 0)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.retry_after_seconds, 30)
        self.assertEqual(RateLimitBucket.objects.get().count, 1)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 60}}
    )
    def test_check_reports_denial_without_consuming(self):
        """
        Report a full bucket without changing its stored count
        """
        now = datetime(2026, 8, 9, 12, 0, 30, tzinfo=datetime_timezone.utc)

        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            consume_rate_limit("registration", "192.0.2.11")
            decision = check_rate_limit("registration", "192.0.2.11")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.retry_after_seconds, 30)
        self.assertEqual(RateLimitBucket.objects.get().count, 1)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 60}}
    )
    def test_check_does_not_delete_expired_buckets(self):
        """
        Keep check_rate_limit free of database cleanup side effects
        """
        identifier_hash = hmac.new(
            settings.SECRET_KEY.encode(),
            b"registration:192.0.2.12",
            hashlib.sha256,
        ).hexdigest()
        RateLimitBucket.objects.create(
            scope="registration",
            identifier_hash=identifier_hash,
            window_seconds=60,
            window_id=0,
            count=1,
            expires_at=datetime(
                2026,
                8,
                9,
                11,
                59,
                tzinfo=datetime_timezone.utc,
            ),
        )
        now = datetime(2026, 8, 9, 12, 0, 30, tzinfo=datetime_timezone.utc)

        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            decision = check_rate_limit("registration", "192.0.2.12")

        self.assertTrue(decision.allowed)
        self.assertEqual(RateLimitBucket.objects.count(), 1)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 2, "window_seconds": 60}}
    )
    def test_consume_retries_when_bucket_disappears_before_lock(self):
        """
        Recover when a concurrent reset deletes the selected bucket
        """
        now = datetime(2026, 8, 9, 12, 0, 30, tzinfo=datetime_timezone.utc)
        missing_bucket = RateLimitBucket.objects.none()
        real_locked_buckets = RateLimitBucket.objects.select_for_update()

        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            with patch.object(
                RateLimitBucket.objects,
                "select_for_update",
                side_effect=[missing_bucket, real_locked_buckets],
            ):
                decision = consume_rate_limit("registration", "192.0.2.13")

        self.assertTrue(decision.allowed)
        self.assertEqual(RateLimitBucket.objects.get().count, 1)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 2, "window_seconds": 60}}
    )
    def test_consume_fails_closed_after_bucket_retry_exhaustion(self):
        """
        Raise DatabaseError after bounded disappearing bucket retries
        """
        now = datetime(2026, 8, 9, 12, 0, 30, tzinfo=datetime_timezone.utc)

        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            with patch.object(
                RateLimitBucket.objects,
                "select_for_update",
                return_value=RateLimitBucket.objects.none(),
            ) as locked_buckets:
                with self.assertRaises(DatabaseError):
                    consume_rate_limit("registration", "192.0.2.14")

        self.assertGreater(locked_buckets.call_count, 1)
        self.assertLessEqual(locked_buckets.call_count, 5)
        self.assertFalse(RateLimitBucket.objects.exists())

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 2, "window_seconds": 60}}
    )
    def test_consume_retries_when_window_changes_before_commit(self):
        """
        Consume only from the new window when time crosses a boundary
        """
        before_boundary = datetime(
            2026,
            8,
            9,
            12,
            0,
            59,
            900000,
            tzinfo=datetime_timezone.utc,
        )
        after_boundary = datetime(
            2026,
            8,
            9,
            12,
            1,
            0,
            tzinfo=datetime_timezone.utc,
        )

        with patch(
            "apps.pages.rate_limits.timezone.now",
            side_effect=[
                before_boundary,
                before_boundary,
                after_boundary,
                after_boundary,
                after_boundary,
                after_boundary,
            ],
        ):
            decision = consume_rate_limit("registration", "192.0.2.15")

        expected_window_id = int(after_boundary.timestamp()) // 60
        bucket = RateLimitBucket.objects.get()
        self.assertTrue(decision.allowed)
        self.assertEqual(bucket.window_id, expected_window_id)
        self.assertEqual(bucket.count, 1)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 2, "window_seconds": 60}}
    )
    def test_consume_keeps_previous_window_and_cleans_older_buckets(self):
        """
        Delay cleanup by one complete window while removing older state
        """
        identifier_hash = hmac.new(
            settings.SECRET_KEY.encode(),
            b"registration:192.0.2.16",
            hashlib.sha256,
        ).hexdigest()
        previous_expiry = datetime(
            2026,
            8,
            9,
            12,
            0,
            tzinfo=datetime_timezone.utc,
        )
        RateLimitBucket.objects.create(
            scope="registration",
            identifier_hash=identifier_hash,
            window_seconds=60,
            window_id=int(previous_expiry.timestamp()) // 60 - 1,
            count=1,
            expires_at=previous_expiry,
        )
        older_expiry = datetime(
            2026,
            8,
            9,
            11,
            59,
            tzinfo=datetime_timezone.utc,
        )
        RateLimitBucket.objects.create(
            scope="registration",
            identifier_hash=identifier_hash,
            window_seconds=60,
            window_id=int(older_expiry.timestamp()) // 60 - 1,
            count=1,
            expires_at=older_expiry,
        )
        now = datetime(2026, 8, 9, 12, 0, 30, tzinfo=datetime_timezone.utc)

        with patch("apps.pages.rate_limits.timezone.now", return_value=now):
            consume_rate_limit("registration", "192.0.2.16")

        expiries = list(
            RateLimitBucket.objects.order_by("expires_at").values_list(
                "expires_at",
                flat=True,
            )
        )
        self.assertIn(previous_expiry, expiries)
        self.assertNotIn(older_expiry, expiries)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 2, "window_seconds": 60}}
    )
    def test_identifier_is_persisted_only_as_hmac_sha256(self):
        """
        Persist only the expected keyed digest for an identifier
        """
        identifier = "198.51.100.24"
        expected_hash = hmac.new(
            settings.SECRET_KEY.encode(),
            f"registration:{identifier}".encode(),
            hashlib.sha256,
        ).hexdigest()

        consume_rate_limit("registration", identifier)

        bucket = RateLimitBucket.objects.get()
        self.assertEqual(bucket.identifier_hash, expected_hash)
        self.assertNotIn(identifier, bucket.identifier_hash)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 60}}
    )
    def test_reset_removes_all_buckets_for_only_the_requested_identifier(self):
        """
        Reset one identifier without removing another identifier's bucket
        """
        first_window = datetime(2026, 8, 9, 12, 0, 0, tzinfo=datetime_timezone.utc)
        second_window = datetime(2026, 8, 9, 12, 2, 0, tzinfo=datetime_timezone.utc)

        with patch("apps.pages.rate_limits.timezone.now", return_value=first_window):
            consume_rate_limit("registration", "192.0.2.20")
            consume_rate_limit("registration", "192.0.2.21")

        with patch("apps.pages.rate_limits.timezone.now", return_value=second_window):
            consume_rate_limit("registration", "192.0.2.20")

        reset_rate_limit("registration", "192.0.2.20")

        self.assertEqual(RateLimitBucket.objects.count(), 1)
        remaining_hash = RateLimitBucket.objects.get().identifier_hash
        self.assertEqual(
            remaining_hash,
            hmac.new(
                settings.SECRET_KEY.encode(),
                b"registration:192.0.2.21",
                hashlib.sha256,
            ).hexdigest(),
        )

    @override_settings(
        RENDER_EXTERNAL_HOSTNAME="pilot.example.onrender.com",
        TRUSTED_PROXY_HOPS=2,
    )
    def test_client_identifier_removes_exactly_the_trusted_proxy_hops(self):
        """
        Select the rightmost address remaining before two trusted proxies
        """
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="198.51.100.10, 203.0.113.7",
            REMOTE_ADDR="203.0.113.8",
        )

        self.assertEqual(get_client_identifier(request), "198.51.100.10")

    @override_settings(
        RENDER_EXTERNAL_HOSTNAME="pilot.example.onrender.com",
        TRUSTED_PROXY_HOPS=1,
    )
    def test_invalid_forwarded_address_falls_back_to_remote_address(self):
        """
        Prevent a malformed forwarded chain from selecting an identifier
        """
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="chosen-by-client, 203.0.113.7",
            REMOTE_ADDR="203.0.113.8",
        )

        self.assertEqual(get_client_identifier(request), "203.0.113.8")

    @override_settings(RENDER_EXTERNAL_HOSTNAME="", TRUSTED_PROXY_HOPS=1)
    def test_valid_attacker_forwarded_address_is_ignored_off_render(self):
        """
        Ignore valid caller supplied forwarding data outside Render
        """
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="198.51.100.99",
            REMOTE_ADDR="203.0.113.8",
        )

        self.assertEqual(get_client_identifier(request), "203.0.113.8")

    @override_settings(TRUSTED_PROXY_HOPS=1)
    def test_missing_forwarded_hops_falls_back_to_remote_address(self):
        """
        Use the remote address when the chain has no client address left
        """
        request = self.factory.get(
            "/",
            REMOTE_ADDR="203.0.113.8",
        )

        self.assertEqual(get_client_identifier(request), "203.0.113.8")


class RateLimitedAccountEndpointTests(TestCase):
    """
    Test rate limiting at registration and password login endpoints
    """

    def _valid_signup(self, username):
        """
        Build valid registration form data for one username

        Parameters
        ----------
        username : str
            Username for the account.

        Returns
        -------
        dict
            Valid registration form data.
        """
        return {
            "username": username,
            "email": f"{username}@example.com",
            "password1": "PublicPilot123!",
            "password2": "PublicPilot123!",
        }

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 3600}}
    )
    def test_second_registration_is_rejected_without_creating_user(self):
        """
        Reject a second same address registration before user creation
        """
        first = self.client.post(
            reverse("register"),
            self._valid_signup("first"),
            REMOTE_ADDR="192.0.2.1",
        )
        second = self.client.post(
            reverse("register"),
            self._valid_signup("second"),
            REMOTE_ADDR="192.0.2.1",
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 429)
        retry_after = int(second.headers["Retry-After"])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 3600)
        self.assertFalse(User.objects.filter(username="second").exists())

    def test_sixth_registration_submission_is_rejected_before_validation(self):
        """
        Enforce the literal production limit of five registration submissions
        """
        invalid_signup = self._valid_signup("unused")
        invalid_signup["password2"] = "different-password"

        for _attempt in range(5):
            response = self.client.post(
                reverse("register"),
                invalid_signup,
                REMOTE_ADDR="192.0.2.2",
            )
            self.assertEqual(response.status_code, 200)

        denied = self.client.post(
            reverse("register"),
            self._valid_signup("sixth"),
            REMOTE_ADDR="192.0.2.2",
        )

        self.assertEqual(denied.status_code, 429)
        self.assertFalse(User.objects.filter(username="sixth").exists())

    def test_eleventh_casefolded_username_login_is_rejected_before_authentication(self):
        """
        Enforce ten attempts across username casing before a valid login
        """
        User.objects.create_user(username="LoginUser", password="ValidPassword123!")

        for attempt in range(10):
            username = "LoginUser" if attempt % 2 == 0 else "LOGINUSER"
            response = self.client.post(
                reverse("login"),
                {"username": username, "password": "wrong-password"},
                REMOTE_ADDR="192.0.2.3",
            )
            self.assertEqual(response.status_code, 200)

        denied = self.client.post(
            reverse("login"),
            {"username": "  LoginUser  ", "password": "ValidPassword123!"},
            REMOTE_ADDR="192.0.2.3",
        )

        self.assertEqual(denied.status_code, 429)
        self.assertIn("Retry-After", denied.headers)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 60}}
    )
    @patch("apps.pages.views.consume_rate_limit", side_effect=DatabaseError)
    def test_registration_database_error_fails_closed(self, _consume):
        """
        Return a generic service error without creating an account
        """
        response = self.client.post(
            reverse("register"),
            self._valid_signup("database-error"),
            REMOTE_ADDR="192.0.2.4",
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(User.objects.filter(username="database-error").exists())

    @override_settings(
        PILOT_RATE_LIMITS={"password_login": {"limit": 1, "window_seconds": 60}}
    )
    @patch("apps.pages.auth_views.consume_rate_limit", side_effect=DatabaseError)
    def test_login_database_error_fails_closed(self, _consume):
        """
        Return a generic service error without authenticating the user
        """
        User.objects.create_user(username="login-error", password="ValidPassword123!")

        response = self.client.post(
            reverse("login"),
            {"username": "login-error", "password": "ValidPassword123!"},
            REMOTE_ADDR="192.0.2.5",
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(
        PILOT_RATE_LIMITS={"registration": {"limit": 1, "window_seconds": 60}}
    )
    def test_accounts_registration_alias_cannot_bypass_limit(self):
        """
        Guard the installed UI package registration path
        """
        first = self.client.post(
            "/accounts/register/",
            self._valid_signup("alias-first"),
            REMOTE_ADDR="192.0.2.30",
        )
        denied = self.client.post(
            "/accounts/register/",
            self._valid_signup("alias-second"),
            REMOTE_ADDR="192.0.2.30",
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(denied.status_code, 429)
        self.assertFalse(User.objects.filter(username="alias-second").exists())

    @override_settings(
        PILOT_RATE_LIMITS={"password_login": {"limit": 1, "window_seconds": 60}}
    )
    def test_accounts_login_alias_cannot_bypass_limit(self):
        """
        Guard the installed UI package password login path
        """
        User.objects.create_user(
            username="alias-login",
            password="ValidPassword123!",
        )
        first = self.client.post(
            "/accounts/login/",
            {"username": "alias-login", "password": "wrong-password"},
            REMOTE_ADDR="192.0.2.31",
        )
        denied = self.client.post(
            "/accounts/login/",
            {"username": "alias-login", "password": "ValidPassword123!"},
            REMOTE_ADDR="192.0.2.31",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(denied.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)


class AdminLoginRateLimitTests(TestCase):
    """
    Test the persistent password limit on the real admin login route
    """

    def test_admin_login_resolves_to_the_pilot_limited_view(self):
        """
        The explicit pilot route shadows Django's unrestricted admin login
        """
        match = resolve("/admin/login/")

        self.assertEqual(match.url_name, "pilot_admin_login")

    @override_settings(
        PILOT_RATE_LIMITS={"password_login": {"limit": 2, "window_seconds": 60}}
    )
    def test_failed_admin_logins_share_one_normalized_password_bucket(self):
        """
        Username casing cannot create separate admin login buckets
        """
        User.objects.create_user(
            username="AdminUser",
            password="ValidPassword123!",
            is_staff=True,
        )

        first = self.client.post(
            "/admin/login/",
            {"username": "AdminUser", "password": "wrong-password"},
            REMOTE_ADDR="192.0.2.40",
        )
        second = self.client.post(
            "/admin/login/",
            {"username": "ADMINUSER", "password": "wrong-password"},
            REMOTE_ADDR="192.0.2.40",
        )
        denied = self.client.post(
            "/admin/login/",
            {"username": " adminuser ", "password": "wrong-password"},
            REMOTE_ADDR="192.0.2.40",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(denied.status_code, 429)
        bucket = RateLimitBucket.objects.get(scope="password_login")
        self.assertEqual(bucket.count, 2)

    @override_settings(
        PILOT_RATE_LIMITS={"password_login": {"limit": 1, "window_seconds": 60}}
    )
    def test_admin_denial_is_generic_and_prevents_authentication(self):
        """
        A full bucket blocks valid staff credentials before authentication
        """
        staff_user = User.objects.create_user(
            username="limited-admin",
            password="ValidPassword123!",
            is_staff=True,
        )
        self.client.post(
            "/admin/login/",
            {"username": staff_user.username, "password": "wrong-password"},
            REMOTE_ADDR="192.0.2.41",
        )

        denied = self.client.post(
            "/admin/login/",
            {
                "username": staff_user.username,
                "password": "ValidPassword123!",
            },
            REMOTE_ADDR="192.0.2.41",
        )

        self.assertEqual(denied.status_code, 429)
        self.assertEqual(denied.content, b"Too many requests.")
        self.assertIn("Retry-After", denied.headers)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_nonstaff_credentials_still_cannot_enter_admin(self):
        """
        The rate limit wrapper preserves Django's staff validation
        """
        user = User.objects.create_user(
            username="ordinary-user",
            password="ValidPassword123!",
        )

        response = self.client.post(
            "/admin/login/",
            {"username": user.username, "password": "ValidPassword123!"},
            REMOTE_ADDR="192.0.2.42",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_credentials_still_log_in_through_admin(self):
        """
        The wrapper delegates successful staff authentication to AdminSite
        """
        staff_user = User.objects.create_user(
            username="staff-user",
            password="ValidPassword123!",
            is_staff=True,
        )

        response = self.client.post(
            "/admin/login/",
            {
                "username": staff_user.username,
                "password": "ValidPassword123!",
            },
            REMOTE_ADDR="192.0.2.43",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            staff_user.pk,
        )

    @patch("apps.pages.auth_views.consume_rate_limit", side_effect=DatabaseError)
    def test_admin_login_database_error_fails_closed(self, _consume):
        """
        A limiter database error blocks admin authentication with 503
        """
        staff_user = User.objects.create_user(
            username="database-admin",
            password="ValidPassword123!",
            is_staff=True,
        )

        response = self.client.post(
            "/admin/login/",
            {
                "username": staff_user.username,
                "password": "ValidPassword123!",
            },
            REMOTE_ADDR="192.0.2.44",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"Service unavailable.")
        self.assertNotIn("_auth_user_id", self.client.session)
