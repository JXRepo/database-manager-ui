import json
from collections import UserDict
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone as datetime_timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

from django.conf import settings
from django.contrib.messages import get_messages
from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import DatabaseError, IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile
from .orcid_auth import (
    ORCID_TRANSACTION_SESSION_KEY,
    ORCIDFlowError,
    ORCIDTransaction,
    _create_orcid_user,
    consume_orcid_transaction,
    normalize_orcid,
    start_orcid_transaction,
)
from .rate_limits import RateLimitDecision


class ORCIDValidationTests(TestCase):
    """Test canonical ORCID identifier validation"""

    def test_numeric_checksum_orcid_is_accepted(self):
        """A canonical ORCID with a numeric checksum is returned unchanged"""
        self.assertEqual(
            normalize_orcid("0000-0002-1451-2715"),
            "0000-0002-1451-2715",
        )

    def test_x_checksum_orcid_is_accepted(self):
        """A canonical ORCID with an X checksum is returned unchanged"""
        self.assertEqual(
            normalize_orcid("0000-0002-1694-233X"),
            "0000-0002-1694-233X",
        )

    def test_malformed_orcid_values_are_rejected(self):
        """Decorated and non-canonical ORCID values cannot become identities"""
        invalid_values = (
            "https://orcid.org/0000-0002-1451-2715",
            "0000000214512715",
            "0000-0002-1694-233x",
            " 0000-0002-1451-2715",
            "0000-0002-1451-2715 ",
            "0000-0002-1451-2715\n",
            "0000‐0002‐1451‐2715",
            "",
            None,
            214512715,
        )

        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ORCIDFlowError):
                normalize_orcid(value)

    def test_wrong_checksum_is_rejected(self):
        """A well-shaped ORCID with the wrong checksum is rejected"""
        with self.assertRaises(ORCIDFlowError):
            normalize_orcid("0000-0002-1451-2716")


class ORCIDTransactionTests(TestCase):
    """Test single-use ORCID OAuth session transactions"""

    now = datetime(2026, 8, 9, 12, 0, tzinfo=datetime_timezone.utc)

    def setUp(self):
        """Create a request with a real Django session"""
        self.request = RequestFactory().get(
            "/login/orcid/",
            HTTP_HOST="testserver",
        )
        SessionMiddleware(lambda request: None).process_request(self.request)

    def _payload(self, **overrides):
        """Build a hand-authored transaction payload for defensive tests"""
        payload = {
            "state": "stored-state",
            "intent": "login",
            "user_id": None,
            "created_at": self.now.timestamp(),
            "next": "/search/",
            "remember_me": False,
        }
        payload.update(overrides)
        return payload

    def _store_payload(self, payload):
        """Put one transaction payload in the request session"""
        self.request.session[ORCID_TRANSACTION_SESSION_KEY] = payload

    def test_start_stores_json_serializable_primitive_payload(self):
        """Starting OAuth replaces state with JSON-safe primitive fields"""
        self._store_payload({"state": "obsolete"})

        with (
            patch(
                "apps.pages.orcid_auth.secrets.token_urlsafe",
                return_value="new-state",
            ) as token_urlsafe,
            patch("apps.pages.orcid_auth.timezone.now", return_value=self.now),
        ):
            state = start_orcid_transaction(
                self.request,
                "link",
                user_id=42,
                next_url="/search/?q=alloys",
            )

        self.assertEqual(state, "new-state")
        token_urlsafe.assert_called_once_with(24)
        payload = self.request.session[ORCID_TRANSACTION_SESSION_KEY]
        self.assertEqual(
            payload,
            {
                "state": "new-state",
                "intent": "link",
                "user_id": 42,
                "created_at": self.now.timestamp(),
                "next": "/search/?q=alloys",
                "remember_me": False,
            },
        )
        self.assertIsInstance(json.dumps(payload), str)
        self.assertNotIsInstance(payload, ORCIDTransaction)

    def test_unknown_start_intent_clears_the_prior_transaction(self):
        """Malformed start intents are rejected without retaining stale state"""
        self._store_payload(self._payload())

        with self.assertRaises(ORCIDFlowError):
            start_orcid_transaction(self.request, "authorize")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_start_rejects_invalid_user_id_types(self):
        """Only integer or absent initiating user identifiers are stored"""
        for user_id in (True, False, "42", 42.0):
            with self.subTest(user_id=user_id), self.assertRaises(ORCIDFlowError):
                start_orcid_transaction(self.request, "link", user_id=user_id)
            self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_callback_transaction_is_consumed_once(self):
        """A successful transaction cannot be replayed"""
        with patch("apps.pages.orcid_auth.timezone.now", return_value=self.now):
            state = start_orcid_transaction(self.request, "login")
            transaction = consume_orcid_transaction(self.request, state)

        self.assertEqual(transaction.state, state)
        self.assertEqual(transaction.intent, "login")
        self.assertIsNone(transaction.user_id)
        self.assertEqual(transaction.next_url, "/search/")
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

        with self.assertRaises(ORCIDFlowError):
            consume_orcid_transaction(self.request, state)

    def test_start_defaults_to_an_unremembered_transaction(self):
        """
        Use an ordinary ORCID session unless the browser explicitly opts in
        """
        state = start_orcid_transaction(self.request, "login")

        self.assertIs(
            self.request.session[ORCID_TRANSACTION_SESSION_KEY].get("remember_me"),
            False,
        )
        consumed = consume_orcid_transaction(self.request, state)
        self.assertIs(consumed.remember_me, False)

    def test_non_boolean_remember_values_are_consumed_before_rejection(self):
        """
        Reject malformed persistence choices without leaving reusable state
        """
        for remember_me in (None, "on", "false", 0, 1, [], {}):
            with self.subTest(remember_me=remember_me):
                self._store_payload(self._payload(remember_me=remember_me))
                with self.assertRaises(ORCIDFlowError):
                    consume_orcid_transaction(self.request, "stored-state")
                self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_start_rejects_non_boolean_remember_values(self):
        """
        Refuse ambiguous persistence choices before creating authorization state
        """
        for remember_me in (None, "on", "false", 0, 1, [], {}):
            with self.subTest(remember_me=remember_me):
                self._store_payload(self._payload())
                with self.assertRaises(ORCIDFlowError):
                    start_orcid_transaction(self.request, "login", remember_me=remember_me)
                self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_missing_remember_choice_is_consumed_before_rejection(self):
        """
        Keep the transaction schema strict when a persistence field is missing
        """
        payload = self._payload()
        payload.pop("remember_me")
        self._store_payload(payload)

        with self.assertRaises(ORCIDFlowError):
            consume_orcid_transaction(self.request, "stored-state")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_returned_transaction_is_frozen(self):
        """Consumed transaction values cannot be changed by later flow code"""
        self._store_payload(self._payload())

        with patch("apps.pages.orcid_auth.timezone.now", return_value=self.now):
            transaction = consume_orcid_transaction(
                self.request,
                "stored-state",
            )

        with self.assertRaises(FrozenInstanceError):
            transaction.intent = "link"

    def test_state_mismatch_consumes_the_transaction(self):
        """A mismatched callback destroys its transaction before rejection"""
        self._store_payload(self._payload())

        with (
            patch("apps.pages.orcid_auth.timezone.now", return_value=self.now),
            self.assertRaises(ORCIDFlowError),
        ):
            consume_orcid_transaction(self.request, "attacker-state")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_non_string_received_state_is_rejected_after_consumption(self):
        """State comparison never receives attacker-controlled non-strings"""
        self._store_payload(self._payload())

        with self.assertRaises(ORCIDFlowError):
            consume_orcid_transaction(self.request, None)

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_non_ascii_received_state_is_rejected_after_consumption(self):
        """A non-ASCII callback state produces a controlled flow error"""
        self._store_payload(self._payload())

        with self.assertRaises(ORCIDFlowError):
            consume_orcid_transaction(self.request, "received-stäte")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_non_ascii_stored_state_is_rejected_after_consumption(self):
        """A tampered non-ASCII stored state produces a controlled flow error"""
        self._store_payload(self._payload(state="stored-stäte"))

        with self.assertRaises(ORCIDFlowError):
            consume_orcid_transaction(self.request, "stored-state")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_malformed_payloads_are_consumed_before_rejection(self):
        """Invalid transaction shapes and types cannot be repaired or retried"""
        malformed_payloads = (
            None,
            "stored-state",
            {},
            self._payload(extra="field"),
            self._payload(state=""),
            self._payload(state=123),
            self._payload(intent="authorize"),
            self._payload(intent=True),
            self._payload(created_at="now"),
            self._payload(created_at=True),
            self._payload(created_at=float("nan")),
            self._payload(created_at=float("inf")),
            self._payload(user_id=True),
            self._payload(user_id="42"),
            self._payload(next=None),
            self._payload(next=""),
        )

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                self._store_payload(payload)
                with self.assertRaises(ORCIDFlowError):
                    consume_orcid_transaction(self.request, "stored-state")
                self.assertNotIn(
                    ORCID_TRANSACTION_SESSION_KEY,
                    self.request.session,
                )

    def test_transaction_exactly_six_hundred_seconds_old_is_valid(self):
        """The ten-minute expiry includes its exact boundary"""
        self._store_payload(
            self._payload(created_at=(self.now - timedelta(seconds=600)).timestamp())
        )

        with patch("apps.pages.orcid_auth.timezone.now", return_value=self.now):
            transaction = consume_orcid_transaction(
                self.request,
                "stored-state",
            )

        self.assertEqual(transaction.next_url, "/search/")

    def test_transaction_over_six_hundred_seconds_old_is_rejected(self):
        """A transaction older than ten minutes is expired"""
        self._store_payload(
            self._payload(
                created_at=(self.now - timedelta(seconds=600.001)).timestamp()
            )
        )

        with (
            patch("apps.pages.orcid_auth.timezone.now", return_value=self.now),
            self.assertRaises(ORCIDFlowError),
        ):
            consume_orcid_transaction(self.request, "stored-state")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_huge_integer_timestamp_is_rejected_after_consumption(self):
        """An unrepresentable integer timestamp produces a controlled error"""
        self._store_payload(self._payload(created_at=10**400))

        with self.assertRaises(ORCIDFlowError):
            consume_orcid_transaction(self.request, "stored-state")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    def test_small_future_clock_skew_is_accepted(self):
        """A timestamp thirty seconds ahead tolerates ordinary host clock skew"""
        self._store_payload(
            self._payload(created_at=(self.now + timedelta(seconds=30)).timestamp())
        )

        with patch("apps.pages.orcid_auth.timezone.now", return_value=self.now):
            transaction = consume_orcid_transaction(
                self.request,
                "stored-state",
            )

        self.assertEqual(transaction.state, "stored-state")

    def test_larger_future_timestamp_is_rejected(self):
        """A timestamp over thirty seconds ahead cannot extend state lifetime"""
        self._store_payload(
            self._payload(created_at=(self.now + timedelta(seconds=30.001)).timestamp())
        )

        with (
            patch("apps.pages.orcid_auth.timezone.now", return_value=self.now),
            self.assertRaises(ORCIDFlowError),
        ):
            consume_orcid_transaction(self.request, "stored-state")

        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.request.session)

    @override_settings(DEBUG=True)
    def test_safe_local_next_target_is_retained(self):
        """A local search target survives transaction creation"""
        state = start_orcid_transaction(
            self.request,
            "login",
            next_url="/search/?q=alloys",
        )

        transaction = consume_orcid_transaction(self.request, state)

        self.assertEqual(transaction.next_url, "/search/?q=alloys")

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["pilot.example"],
    )
    def test_same_host_https_next_target_is_retained_in_production(self):
        """A production HTTPS target on the current host remains usable"""
        request = RequestFactory().get(
            "/login/orcid/",
            secure=True,
            HTTP_HOST="pilot.example",
        )
        SessionMiddleware(lambda current_request: None).process_request(request)

        state = start_orcid_transaction(
            request,
            "login",
            next_url="https://pilot.example/search/?q=alloys",
        )
        transaction = consume_orcid_transaction(request, state)

        self.assertEqual(
            transaction.next_url,
            "https://pilot.example/search/?q=alloys",
        )

    @override_settings(DEBUG=True)
    def test_unsafe_next_targets_use_search_default(self):
        """External and browser-confusing redirect targets are discarded"""
        unsafe_targets = (
            "https://evil.example/",
            "//evil.example/",
            "//testserver/search/",
            r"\\evil.example\search",
            r"/\evil.example/search",
            r"https:\\evil.example\search",
        )

        for next_url in unsafe_targets:
            with self.subTest(next_url=next_url):
                state = start_orcid_transaction(
                    self.request,
                    "login",
                    next_url=next_url,
                )
                transaction = consume_orcid_transaction(self.request, state)
                self.assertEqual(transaction.next_url, "/search/")

    @override_settings(DEBUG=True)
    def test_consume_resanitizes_tampered_unsafe_next_targets(self):
        """
        Consume rejects unsafe next values changed after transaction start
        """
        unsafe_targets = (
            "https://evil.example/phish",
            "//evil.example/phish",
            r"/\evil.example/phish",
        )

        for next_url in unsafe_targets:
            with self.subTest(next_url=next_url):
                state = start_orcid_transaction(
                    self.request,
                    "login",
                    next_url="/search/?initial=safe",
                )
                payload = dict(
                    self.request.session[ORCID_TRANSACTION_SESSION_KEY]
                )
                payload["next"] = next_url
                self.request.session[ORCID_TRANSACTION_SESSION_KEY] = payload

                transaction = consume_orcid_transaction(self.request, state)

                self.assertEqual(transaction.next_url, "/search/")
                self.assertNotIn(
                    ORCID_TRANSACTION_SESSION_KEY,
                    self.request.session,
                )

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["pilot.example"],
    )
    def test_production_http_downgrade_uses_search_default(self):
        """Production does not redirect from HTTPS to an HTTP next target"""
        request = RequestFactory().get(
            "/login/orcid/",
            secure=True,
            HTTP_HOST="pilot.example",
        )
        SessionMiddleware(lambda current_request: None).process_request(request)

        state = start_orcid_transaction(
            request,
            "login",
            next_url="http://pilot.example/search/",
        )
        transaction = consume_orcid_transaction(request, state)

        self.assertEqual(transaction.next_url, "/search/")

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["pilot.example"],
    )
    def test_consume_resanitizes_tampered_production_http_downgrade(self):
        """
        Consume rejects a stored HTTP downgrade changed after secure start
        """
        request = RequestFactory().get(
            "/login/orcid/",
            secure=True,
            HTTP_HOST="pilot.example",
        )
        SessionMiddleware(lambda current_request: None).process_request(request)
        state = start_orcid_transaction(
            request,
            "login",
            next_url="https://pilot.example/search/?initial=safe",
        )
        payload = dict(request.session[ORCID_TRANSACTION_SESSION_KEY])
        payload["next"] = "http://pilot.example/search/?tampered=true"
        request.session[ORCID_TRANSACTION_SESSION_KEY] = payload

        transaction = consume_orcid_transaction(request, state)

        self.assertEqual(transaction.next_url, "/search/")
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, request.session)


@override_settings(
    ORCID_CLIENT_ID="APP-TEST",
    ORCID_CLIENT_SECRET="super-secret-value",
    ORCID_BASE_URL="https://sandbox.orcid.org",
    ORCID_REDIRECT_URI="https://pilot.example/settings/orcid/callback/",
)
class ORCIDStartTests(TestCase):
    """
    Test safe starts for ORCID login and account linking
    """

    def setUp(self):
        """
        Create a local user and an allowed limiter decision
        """
        self.user = User.objects.create_user(
            username="orcid-start-user",
            password="password",
        )
        limiter_patcher = patch(
            "apps.pages.views.consume_rate_limit",
            return_value=RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
            ),
        )
        self.consume_rate_limit = limiter_patcher.start()
        self.addCleanup(limiter_patcher.stop)

    def _transaction(self):
        """
        Return the transaction stored by the most recent start
        """
        return self.client.session[ORCID_TRANSACTION_SESSION_KEY]

    def _store_stale_transaction(self):
        """
        Put an obsolete transaction in the client session
        """
        session = self.client.session
        session[ORCID_TRANSACTION_SESSION_KEY] = {
            "state": "obsolete-state",
            "intent": "login",
            "user_id": None,
            "created_at": 1,
            "next": "/obsolete/",
            "remember_me": False,
        }
        session.save()

    def test_anonymous_login_start_records_login_intent(self):
        """
        Anonymous login starts a login transaction with no local user
        """
        response = self.client.get(
            reverse("orcid_login"),
            REMOTE_ADDR="192.0.2.40",
        )

        self.assertEqual(response.status_code, 302)
        transaction = self._transaction()
        self.assertEqual(transaction["intent"], "login")
        self.assertIsNone(transaction["user_id"])
        self.consume_rate_limit.assert_called_once_with(
            "orcid_start",
            "192.0.2.40",
        )

    def test_authorization_redirect_has_exact_provider_contract(self):
        """
        The provider redirect contains only the required public OAuth values
        """
        response = self.client.get(reverse("orcid_login"))

        location = urlsplit(response["Location"])
        query = parse_qs(location.query, keep_blank_values=True)
        self.assertEqual(location.scheme, "https")
        self.assertEqual(location.netloc, "sandbox.orcid.org")
        self.assertEqual(location.path, "/oauth/authorize")
        self.assertEqual(
            query,
            {
                "client_id": ["APP-TEST"],
                "response_type": ["code"],
                "scope": ["/authenticate"],
                "redirect_uri": [
                    "https://pilot.example/settings/orcid/callback/"
                ],
                "state": [self._transaction()["state"]],
            },
        )
        self.assertNotIn("client_secret", query)
        self.assertNotIn("super-secret-value", response["Location"])

    def test_connect_requires_login_without_consuming_a_limit(self):
        """
        Anonymous users cannot start the account linking intent
        """
        response = self.client.get(reverse("orcid_connect"))

        self.assertRedirects(
            response,
            f'/login/?next={reverse("orcid_connect")}',
        )
        self.assertNotIn(
            ORCID_TRANSACTION_SESSION_KEY,
            self.client.session,
        )
        self.consume_rate_limit.assert_not_called()

    def test_authenticated_connect_records_link_intent_and_user(self):
        """
        Linking records the signed in user without changing the limiter key
        """
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("orcid_connect"),
            REMOTE_ADDR="198.51.100.7",
        )

        self.assertEqual(response.status_code, 302)
        transaction = self._transaction()
        self.assertEqual(transaction["intent"], "link")
        self.assertEqual(transaction["user_id"], self.user.pk)
        self.consume_rate_limit.assert_called_once_with(
            "orcid_start",
            "198.51.100.7",
        )

    def test_start_routes_accept_get_only(self):
        """
        POST cannot create login or link transactions
        """
        login_response = self.client.post(reverse("orcid_login"))
        self.client.force_login(self.user)
        link_response = self.client.post(reverse("orcid_connect"))

        self.assertEqual(login_response.status_code, 405)
        self.assertEqual(link_response.status_code, 405)
        self.assertNotIn(
            ORCID_TRANSACTION_SESSION_KEY,
            self.client.session,
        )
        self.consume_rate_limit.assert_not_called()

    def test_login_missing_configuration_clears_stale_transaction(self):
        """
        Missing login credentials return locally without an OAuth transaction
        """
        self._store_stale_transaction()

        with override_settings(ORCID_CLIENT_ID=" "):
            response = self.client.get(reverse("orcid_login"))

        self.assertRedirects(response, "/login/")
        self.assertNotIn(
            ORCID_TRANSACTION_SESSION_KEY,
            self.client.session,
        )
        self.consume_rate_limit.assert_not_called()

    def test_connect_missing_configuration_clears_stale_transaction(self):
        """
        Missing link credentials return to settings without stale state
        """
        self.client.force_login(self.user)
        self._store_stale_transaction()

        with override_settings(ORCID_CLIENT_SECRET=" "):
            response = self.client.get(reverse("orcid_connect"))

        self.assertRedirects(response, reverse("account_settings"))
        self.assertNotIn(
            ORCID_TRANSACTION_SESSION_KEY,
            self.client.session,
        )
        self.consume_rate_limit.assert_not_called()

    def test_rate_limit_denial_returns_generic_response_without_state(self):
        """
        A denied configured start has a positive retry delay and no redirect
        """
        self._store_stale_transaction()
        self.consume_rate_limit.return_value = RateLimitDecision(
            allowed=False,
            retry_after_seconds=37,
        )

        response = self.client.get(
            reverse("orcid_login"),
            REMOTE_ADDR="203.0.113.9",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.content, b"Too many requests.")
        self.assertEqual(response.headers["Retry-After"], "37")
        self.assertNotIn("Location", response.headers)
        self.assertNotIn(
            ORCID_TRANSACTION_SESSION_KEY,
            self.client.session,
        )
        self.consume_rate_limit.assert_called_once_with(
            "orcid_start",
            "203.0.113.9",
        )

    def test_rate_limit_database_error_returns_generic_response_without_state(self):
        """
        A limiter database failure returns no redirect or OAuth transaction
        """
        self._store_stale_transaction()
        self.consume_rate_limit.side_effect = DatabaseError(
            "database includes super-secret-value"
        )

        response = self.client.get(reverse("orcid_login"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"Service unavailable.")
        self.assertNotIn("Location", response.headers)
        self.assertNotContains(response, "super-secret-value", status_code=503)
        self.assertNotIn(
            ORCID_TRANSACTION_SESSION_KEY,
            self.client.session,
        )

    def test_second_successful_start_replaces_the_first_transaction(self):
        """
        Only the latest successful start remains valid in the session
        """
        first_response = self.client.get(reverse("orcid_login"))
        first_state = parse_qs(
            urlsplit(first_response["Location"]).query
        )["state"][0]

        second_response = self.client.get(reverse("orcid_login"))
        second_state = parse_qs(
            urlsplit(second_response["Location"]).query
        )["state"][0]

        self.assertNotEqual(first_state, second_state)
        self.assertEqual(self._transaction()["state"], second_state)
        self.assertNotIn("orcid_oauth_state", self.client.session)
        self.assertEqual(self.consume_rate_limit.call_count, 2)

    def test_next_target_is_sanitized_when_the_start_transaction_is_created(self):
        """
        Safe local next targets survive while hostile targets use Search
        """
        self.client.get(
            reverse("orcid_login"),
            {"next": "/search/?keyword=alloys"},
        )
        self.assertEqual(
            self._transaction()["next"],
            "/search/?keyword=alloys",
        )

        self.client.get(
            reverse("orcid_login"),
            {"next": "https://evil.example/private"},
        )
        self.assertEqual(self._transaction()["next"], "/search/")

    def test_login_template_keeps_local_login_and_adds_encoded_orcid_link(self):
        """
        Login keeps password and registration controls beside a normal ORCID link
        """
        response = self.client.get(
            reverse("login"),
            {"next": "/search/?keyword=alloys"},
        )

        expected_orcid_url = (
            f'{reverse("orcid_login")}'
            "?next=/search/%3Fkeyword%3Dalloys"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{expected_orcid_url}"',
            html=False,
        )
        self.assertContains(response, "Sign in with ORCID")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, reverse("register"))


class ORCIDCallbackTestMixin:
    """
    Provide real session and database helpers for callback tests
    """

    authorization_code = "private-authorization-code"
    access_token = "private-provider-token"
    provider_name = "Private Provider Name"
    provider_email = "private-provider@example.com"
    provider_token_type = "private-provider-token-type"
    primary_orcid = "0000-0002-1451-2715"
    secondary_orcid = "0000-0002-1694-233X"

    def setUp(self):
        """
        Replace external provider calls while retaining real account resolution
        """
        super().setUp()
        exchange_patcher = patch(
            "apps.pages.views._exchange_orcid_authorization_code"
        )
        self.exchange = exchange_patcher.start()
        self.addCleanup(exchange_patcher.stop)
        self.exchange.return_value = self._provider_payload()
        profile_patcher = patch("requests.get")
        self.profile_request = profile_patcher.start()
        self.addCleanup(profile_patcher.stop)
        response = self.profile_request.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [b"{}"]

    def _provider_payload(self, **overrides):
        """
        Return one complete provider payload

        Parameters
        ----------
        **overrides : dict
            Values that replace fields in the standard provider payload.

        Returns
        -------
        dict
            Complete provider response data for one callback.
        """
        payload = {
            "access_token": self.access_token,
            "orcid": self.primary_orcid,
            "name": self.provider_name,
            "email": self.provider_email,
            "token_type": self.provider_token_type,
        }
        payload.update(overrides)
        return payload

    def _store_transaction(
        self,
        *,
        state="callback-state",
        intent="login",
        user_id=None,
        next_url="/search/",
        created_at=None,
    ):
        """
        Store one callback transaction in the real client session

        Parameters
        ----------
        state : str
            OAuth state stored before the callback.
        intent : str
            Login or link action recorded at the start.
        user_id : int or None
            Local user that initiated a link action.
        next_url : str
            Sanitized local success target.
        created_at : float or None
            Transaction timestamp, or the current time when omitted.

        Returns
        -------
        str
            Stored OAuth state.
        """
        if created_at is None:
            created_at = timezone.now().timestamp()

        session = self.client.session
        session[ORCID_TRANSACTION_SESSION_KEY] = {
            "state": state,
            "intent": intent,
            "user_id": user_id,
            "created_at": created_at,
            "next": next_url,
            "remember_me": False,
        }
        session.save()
        return state

    def _request_callback(
        self,
        query,
        *,
        intent="login",
        user_id=None,
        next_url="/search/",
        created_at=None,
        include_state=True,
    ):
        """
        Call the callback with a freshly stored real transaction

        Parameters
        ----------
        query : dict
            Callback query parameters other than the default state.
        intent : str
            Stored transaction intent.
        user_id : int or None
            Stored initiating user for link transactions.
        next_url : str
            Stored sanitized local next target.
        created_at : float or None
            Stored transaction time.
        include_state : bool
            Whether to add the matching state parameter.

        Returns
        -------
        HttpResponse
            Callback response from Django's test client.
        """
        state = self._store_transaction(
            intent=intent,
            user_id=user_id,
            next_url=next_url,
            created_at=created_at,
        )
        callback_query = dict(query)
        if include_state:
            callback_query.setdefault("state", state)
        return self.client.get(reverse("orcid_callback"), callback_query)

    def _complete_login(self, payload=None, *, next_url="/search/"):
        """
        Complete one valid login callback

        Parameters
        ----------
        payload : dict or None
            Provider response, or the standard complete payload when omitted.
        next_url : str
            Sanitized local redirect stored by the transaction.

        Returns
        -------
        HttpResponse
            Callback response after real login resolution.
        """
        if payload is not None:
            self.exchange.return_value = payload
        return self._request_callback(
            {"code": self.authorization_code},
            next_url=next_url,
        )

    def _start_then_tamper_next(
        self,
        next_url,
        *,
        secure=False,
        host="testserver",
    ):
        """
        Start a real login transaction and replace its stored next value

        Parameters
        ----------
        next_url : str
            Value written after the start route stores a safe transaction.
        secure : bool
            Whether both requests use HTTPS.
        host : str
            Host used by the start and callback requests.

        Returns
        -------
        str
            OAuth state stored by the real start route.
        """
        start_response = self.client.get(
            reverse("orcid_login"),
            {"next": "/search/?initial=safe"},
            secure=secure,
            HTTP_HOST=host,
        )
        self.assertEqual(start_response.status_code, 302)

        session = self.client.session
        payload = dict(session[ORCID_TRANSACTION_SESSION_KEY])
        state = payload["state"]
        payload["next"] = next_url
        session[ORCID_TRANSACTION_SESSION_KEY] = payload
        session.save()
        return state

    def _response_artifacts(self, response):
        """
        Return user-visible, session, and identity storage artifacts

        Parameters
        ----------
        response : HttpResponse
            Callback response to inspect.

        Returns
        -------
        str
            Combined representation that must not contain provider secrets.
        """
        message_text = " ".join(
            str(message) for message in get_messages(response.wsgi_request)
        )
        return "\n".join(
            (
                response.content.decode("utf-8", errors="replace"),
                repr(dict(response.headers)),
                repr(response.cookies),
                message_text,
                repr(dict(self.client.session)),
                repr(
                    list(
                        User.objects.values(
                            "username",
                            "first_name",
                            "last_name",
                            "email",
                            "is_staff",
                            "is_superuser",
                        )
                    )
                ),
                repr(
                    list(
                        AccountProfile.objects.values(
                            "institution",
                            "orcid",
                            "authenticated_orcid",
                        )
                    )
                ),
            )
        )

    def _assert_sensitive_values_absent(self, response, *values):
        """
        Assert provider secrets are absent from local artifacts

        Parameters
        ----------
        response : HttpResponse
            Callback response to inspect.
        *values : tuple[str]
            Sensitive literal values that must not appear.

        Returns
        -------
        str
            Combined artifacts for additional fixed-message assertions.
        """
        artifacts = self._response_artifacts(response)
        for value in values:
            with self.subTest(sensitive_value=value):
                self.assertNotIn(value, artifacts)
        return artifacts


@override_settings(
    ORCID_CLIENT_ID="APP-TEST",
    ORCID_CLIENT_SECRET="private-client-secret",
    ORCID_REDIRECT_URI="https://pilot.example/settings/orcid/callback/",
)
class ORCIDLoginCallbackTests(ORCIDCallbackTestMixin, TestCase):
    """
    Test verified ORCID login identity resolution
    """

    def _create_verified_user(
        self,
        username,
        orcid=None,
        *,
        is_active=True,
    ):
        """
        Create one local account with a verified ORCID identity

        Parameters
        ----------
        username : str
            Local username.
        orcid : str or None
            Verified identity, defaulting to the primary fixture.
        is_active : bool
            Whether Django may authenticate the account.

        Returns
        -------
        User
            Created local user.
        """
        user = User.objects.create_user(
            username=username,
            password="local-password",
            is_active=is_active,
        )
        AccountProfile.objects.create(
            user=user,
            authenticated_orcid=orcid or self.primary_orcid,
            orcid_authenticated_at=timezone.now(),
        )
        return user

    def test_existing_active_identity_logs_in_exact_user(self):
        """
        An active verified identity logs in its exact local account
        """
        user = self._create_verified_user("existing-orcid-user")

        response = self._complete_login()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/search/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(User.objects.count(), 1)
        self.exchange.assert_called_once_with(
            self.authorization_code,
            "https://pilot.example/settings/orcid/callback/",
        )

    def test_inactive_verified_identity_is_rejected_without_replacement(self):
        """
        An inactive verified identity cannot log in or gain a replacement
        """
        inactive_user = self._create_verified_user(
            "inactive-orcid-user",
            is_active=False,
        )

        response = self._complete_login()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], settings.LOGIN_URL)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(
            AccountProfile.objects.get().user_id,
            inactive_user.pk,
        )

    def test_first_verified_login_creates_passwordless_ordinary_user(self):
        """
        First login creates one minimal ordinary local account
        """
        response = self._complete_login()

        profile = AccountProfile.objects.select_related("user").get(
            authenticated_orcid=self.primary_orcid
        )
        user = profile.user
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(user.username, "orcid_0000000214512715")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.email, "")
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIsNotNone(profile.orcid_authenticated_at)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self._assert_sensitive_values_absent(
            response,
            self.authorization_code,
            self.access_token,
            settings.ORCID_CLIENT_SECRET,
            self.provider_name,
            self.provider_email,
            self.provider_token_type,
        )

    def test_repeated_login_reuses_the_created_identity(self):
        """
        Later callbacks reuse the first account instead of duplicating it
        """
        first_response = self._complete_login()
        first_profile = AccountProfile.objects.get(
            authenticated_orcid=self.primary_orcid
        )
        self.assertEqual(first_response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.client.logout()

        second_response = self._complete_login()

        self.assertEqual(second_response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(AccountProfile.objects.count(), 1)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            first_profile.user_id,
        )
        self.assertEqual(self.exchange.call_count, 2)

    def test_derived_username_collision_uses_numeric_suffix_without_linking(self):
        """
        An occupied derived username gains a suffix and is never linked
        """
        occupied = User.objects.create_user(
            username="orcid_0000000214512715",
            password="local-password",
        )

        response = self._complete_login()

        profile = AccountProfile.objects.select_related("user").get(
            authenticated_orcid=self.primary_orcid
        )
        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(profile.user.username, "orcid_0000000214512715_2")
        self.assertNotEqual(profile.user_id, occupied.pk)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            profile.user_id,
        )

    def test_exact_legacy_claim_blocks_creation_and_authentication(self):
        """
        An exact legacy claim requires local login and explicit Connect
        """
        legacy_user = User.objects.create_user(
            username="legacy-claim-user",
            password="local-password",
        )
        legacy_profile = AccountProfile.objects.create(
            user=legacy_user,
            orcid=self.primary_orcid,
        )

        response = self._complete_login()

        legacy_profile.refresh_from_db()
        self.assertEqual(response["Location"], settings.LOGIN_URL)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(legacy_profile.orcid, self.primary_orcid)
        self.assertIsNone(legacy_profile.authenticated_orcid)
        artifacts = self._response_artifacts(response)
        self.assertIn("Sign in locally", artifacts)
        self.assertIn("Connect ORCID", artifacts)

    def test_provider_name_and_email_never_associate_a_local_account(self):
        """
        Matching provider profile data cannot select a local account
        """
        matching_user = User.objects.create_user(
            username=self.provider_name,
            email=self.provider_email,
            first_name="Private Provider",
            last_name="Name",
            password="local-password",
        )

        response = self._complete_login()

        profile = AccountProfile.objects.select_related("user").get(
            authenticated_orcid=self.primary_orcid
        )
        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertNotEqual(profile.user_id, matching_user.pk)
        self.assertEqual(profile.user.email, "")
        self.assertEqual(profile.user.first_name, "")
        self.assertEqual(profile.user.last_name, "")
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            profile.user_id,
        )

    def test_identity_race_logs_in_committed_winner_without_orphan(self):
        """
        A losing identity insert authenticates the committed race winner
        """
        def simulate_identity_race(orcid):
            """
            Commit a winner and roll back one losing account insert

            Parameters
            ----------
            orcid : str
                Verified identity claimed by both simulated callbacks.
            """
            winner = User.objects.create_user(username="race-winner")
            AccountProfile.objects.create(
                user=winner,
                authenticated_orcid=orcid,
                orcid_authenticated_at=timezone.now(),
            )
            with transaction.atomic():
                User.objects.create(username="orcid_0000000214512715")
                raise IntegrityError("simulated identity race")

        with patch(
            "apps.pages.orcid_auth._create_orcid_user",
            side_effect=simulate_identity_race,
        ):
            response = self._complete_login()

        winner = User.objects.get(username="race-winner")
        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(int(self.client.session["_auth_user_id"]), winner.pk)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(AccountProfile.objects.count(), 1)

    def test_real_creation_rolls_back_user_when_profile_insert_fails(self):
        """
        The real creation helper leaves no user after profile insert failure
        """
        derived_username = "orcid_0000000214512715"

        with patch(
            "apps.pages.orcid_auth.AccountProfile.objects.create",
            side_effect=IntegrityError("simulated profile identity conflict"),
        ):
            with self.assertRaises(IntegrityError):
                _create_orcid_user(self.primary_orcid)

        self.assertFalse(
            User.objects.filter(username=derived_username).exists()
        )
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(AccountProfile.objects.count(), 0)

    def test_identity_integrity_error_without_winner_is_controlled(self):
        """
        An unexplained identity integrity failure does not return a 500
        """
        with patch(
            "apps.pages.orcid_auth._create_orcid_user",
            side_effect=IntegrityError("private database detail"),
        ):
            response = self._complete_login()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], settings.LOGIN_URL)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 0)
        self.assertNotIn(
            "private database detail",
            self._response_artifacts(response),
        )

    def test_success_uses_the_sanitized_transaction_next_target(self):
        """
        Successful login redirects only to the stored safe next target
        """
        response = self._complete_login(next_url="/search/?keyword=alloys")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "/settings/orcid/setup/?next=%2Fsearch%2F%3Fkeyword%3Dalloys",
        )

    @override_settings(DEBUG=True)
    def test_callback_resanitizes_tampered_unsafe_next_targets(self):
        """
        Real login callbacks never redirect to a tampered external target
        """
        unsafe_targets = (
            "https://evil.example/phish",
            "//evil.example/phish",
            r"/\evil.example/phish",
        )

        for next_url in unsafe_targets:
            with self.subTest(next_url=next_url):
                self.client.logout()
                state = self._start_then_tamper_next(next_url)

                response = self.client.get(
                    reverse("orcid_callback"),
                    {
                        "state": state,
                        "code": self.authorization_code,
                    },
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F"
                )
                self.assertEqual(urlsplit(response["Location"]).netloc, "")
                self.assertNotIn(
                    ORCID_TRANSACTION_SESSION_KEY,
                    self.client.session,
                )

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["pilot.example"],
    )
    def test_callback_resanitizes_tampered_production_http_downgrade(self):
        """
        A secure callback rejects a tampered same host HTTP downgrade
        """
        state = self._start_then_tamper_next(
            "http://pilot.example/search/?tampered=true",
            secure=True,
            host="pilot.example",
        )

        response = self.client.get(
            reverse("orcid_callback"),
            {
                "state": state,
                "code": self.authorization_code,
            },
            secure=True,
            HTTP_HOST="pilot.example",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(urlsplit(response["Location"]).netloc, "")
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["pilot.example"],
    )
    def test_callback_preserves_valid_same_host_https_next(self):
        """
        A secure callback retains a valid same host HTTPS next target
        """
        next_url = "https://pilot.example/search/?keyword=alloys"
        state = self._start_then_tamper_next(
            next_url,
            secure=True,
            host="pilot.example",
        )

        response = self.client.get(
            reverse("orcid_callback"),
            {
                "state": state,
                "code": self.authorization_code,
            },
            secure=True,
            HTTP_HOST="pilot.example",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], "/settings/orcid/setup/?" + urlencode({"next": next_url})
        )
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)

    def test_authenticated_same_identity_is_idempotent(self):
        """
        A signed in user may repeat only their own verified identity
        """
        user = self._create_verified_user("current-orcid-user")
        self.client.force_login(user)

        response = self._complete_login(next_url="/search/?owner=current")

        self.assertEqual(response["Location"], "/search/?owner=current")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_authenticated_different_identity_never_switches_accounts(self):
        """
        A signed in browser cannot switch to another verified identity
        """
        current_user = self._create_verified_user(
            "current-user",
            orcid=self.secondary_orcid,
        )
        other_user = self._create_verified_user("other-user")
        self.client.force_login(current_user)

        response = self._complete_login()

        self.assertEqual(response["Location"], reverse("account_settings"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            current_user.pk,
        )
        self.assertNotEqual(current_user.pk, other_user.pk)
        self.assertEqual(User.objects.count(), 2)

    def test_authenticated_unbound_identity_never_creates_or_links(self):
        """
        A signed in browser cannot create or bind an unknown identity
        """
        current_user = User.objects.create_user(
            username="unbound-current-user",
            password="local-password",
        )
        current_profile = AccountProfile.objects.create(user=current_user)
        self.client.force_login(current_user)

        response = self._complete_login()

        current_profile.refresh_from_db()
        self.assertEqual(response["Location"], reverse("account_settings"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            current_user.pk,
        )
        self.assertIsNone(current_profile.authenticated_orcid)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(AccountProfile.objects.count(), 1)


@override_settings(
    ORCID_CLIENT_ID="APP-TEST",
    ORCID_CLIENT_SECRET="private-client-secret",
    ORCID_REDIRECT_URI="https://pilot.example/settings/orcid/callback/",
)
class ORCIDLinkCallbackTests(ORCIDCallbackTestMixin, TestCase):
    """Test explicit verified ORCID account linking"""

    def setUp(self):
        """Create two local accounts with distinct legacy profile data"""
        super().setUp()
        self.user = User.objects.create_user(
            username="link-current-user",
            email="current@example.com",
            password="current-password",
        )
        self.other = User.objects.create_user(
            username="link-other-user",
            email="other@example.com",
            password="other-password",
        )
        self.profile = AccountProfile.objects.create(
            user=self.user,
            institution="Current Institute",
            orcid="legacy-current-orcid",
        )
        self.other_profile = AccountProfile.objects.create(
            user=self.other,
            institution="Other Institute",
            orcid="legacy-other-orcid",
        )
        self.client.force_login(self.user)

    def _profile_state(self):
        """Return all profile identity fields in stable account order"""
        return list(
            AccountProfile.objects.order_by("user_id").values(
                "user_id",
                "institution",
                "orcid",
                "authenticated_orcid",
                "orcid_authenticated_at",
            )
        )

    def _user_state(self):
        """Return all local account fields in stable account order"""
        return list(
            User.objects.order_by("pk").values(
                "pk",
                "username",
                "first_name",
                "last_name",
                "email",
                "password",
                "is_active",
                "is_staff",
                "is_superuser",
            )
        )

    def _complete_link(self, *, user_id=None, orcid=None):
        """Complete one valid provider callback with link intent"""
        if orcid is not None:
            self.exchange.return_value = self._provider_payload(orcid=orcid)
        if user_id is None:
            user_id = self.user.pk

        response = self._request_callback(
            {"code": self.authorization_code},
            intent="link",
            user_id=user_id,
        )
        persisted_state = "\n".join(
            (
                repr(dict(self.client.session)),
                repr(self._user_state()),
                repr(self._profile_state()),
            )
        )
        self.assertNotIn(self.access_token, persisted_state)
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        return response

    def _assert_link_refused(
        self, response, expected_message="ORCID account linking could not be completed."
    ):
        """
        Assert a refused link returns the expected guidance without private data

        Parameters
        ----------
        response : HttpResponse
            Response from the completed linking callback.
        expected_message : str, optional
            Guidance appropriate to the reason for refusing the link.

        Returns
        -------
        str
            Response and stored account artifacts checked for sensitive values.
        """
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_settings"))
        artifacts = self._assert_sensitive_values_absent(
            response,
            self.authorization_code,
            self.access_token,
            settings.ORCID_CLIENT_SECRET,
            self.provider_name,
            self.provider_email,
            self.provider_token_type,
        )
        self.assertIn(expected_message, artifacts)
        return artifacts

    def _assert_link_succeeded(self, response):
        """Assert one link attempt returned a private local success"""
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_settings"))
        artifacts = self._assert_sensitive_values_absent(
            response,
            self.authorization_code,
            self.access_token,
            settings.ORCID_CLIENT_SECRET,
            self.provider_name,
            self.provider_email,
            self.provider_token_type,
        )
        self.assertIn("ORCID iD connected.", artifacts)

    def _assert_current_session_user(self, user):
        """Assert the callback did not switch the authenticated session"""
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_callback_session_must_match_the_initiating_user(self):
        """Switching accounts after link start cannot bind the identity"""
        before_profiles = self._profile_state()
        self.client.force_login(self.other)

        response = self._complete_link(user_id=self.user.pk)

        self._assert_link_refused(response)
        self._assert_current_session_user(self.other)
        self.assertEqual(self._profile_state(), before_profiles)

    def test_logged_out_callback_cannot_link_or_authenticate_an_account(self):
        """Logging out after link start cannot mutate or sign in an account"""
        before_profiles = self._profile_state()
        before_users = self._user_state()
        self.client.logout()

        response = self._complete_link(user_id=self.user.pk)

        self._assert_link_refused(response)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self._profile_state(), before_profiles)
        self.assertEqual(self._user_state(), before_users)

    def test_inactive_callback_account_cannot_link_an_identity(self):
        """An account deactivated after link start cannot gain an identity"""
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        before_profiles = self._profile_state()
        before_users = self._user_state()

        response = self._complete_link(user_id=self.user.pk)

        self._assert_link_refused(response)
        self.assertEqual(self._profile_state(), before_profiles)
        self.assertEqual(self._user_state(), before_users)

    def test_link_cannot_take_identity_from_another_user(self):
        """
        Keep the original binding and explain how to disconnect it first
        """
        other_linked_at = timezone.now() - timedelta(days=2)
        self.other_profile.authenticated_orcid = self.primary_orcid
        self.other_profile.orcid_authenticated_at = other_linked_at
        self.other_profile.save(
            update_fields=["authenticated_orcid", "orcid_authenticated_at"]
        )
        before_profiles = self._profile_state()

        response = self._complete_link()

        self._assert_link_refused(
            response,
            "This ORCID iD is already connected to another account. "
            "Please sign in to that account and disconnect it in Settings "
            "before connecting it here.",
        )
        settings_page = self.client.get(reverse("account_settings"))
        self.assertContains(settings_page, "already connected to another account")
        self.assertNotContains(settings_page, self.other.username)
        self.assertNotContains(settings_page, self.other.email)
        self._assert_current_session_user(self.user)
        self.assertEqual(self._profile_state(), before_profiles)

    def test_linking_the_same_identity_twice_is_timestamp_stable(self):
        """Repeated linking of the same identity is an idempotent success"""
        first_linked_at = timezone.now() - timedelta(days=1)
        self.profile.authenticated_orcid = self.primary_orcid
        self.profile.orcid_authenticated_at = first_linked_at
        self.profile.save(
            update_fields=["authenticated_orcid", "orcid_authenticated_at"]
        )
        before_users = self._user_state()
        other_before = self._profile_state()[1]

        first_response = self._complete_link()
        self._assert_link_succeeded(first_response)
        second_response = self._complete_link()
        self._assert_link_succeeded(second_response)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, self.primary_orcid)
        self.assertEqual(self.profile.orcid_authenticated_at, first_linked_at)
        self.assertEqual(self.profile.orcid, "legacy-current-orcid")
        self.assertEqual(self.profile.institution, "Current Institute")
        self.assertEqual(self._profile_state()[1], other_before)
        self.assertEqual(self._user_state(), before_users)
        self._assert_current_session_user(self.user)

    def test_existing_verified_identity_cannot_be_replaced(self):
        """A different verified identity is refused without an overwrite"""
        linked_at = timezone.now() - timedelta(days=3)
        self.profile.authenticated_orcid = self.secondary_orcid
        self.profile.orcid_authenticated_at = linked_at
        self.profile.save(
            update_fields=["authenticated_orcid", "orcid_authenticated_at"]
        )
        before_profiles = self._profile_state()

        response = self._complete_link()

        self._assert_link_refused(response)
        self._assert_current_session_user(self.user)
        self.assertEqual(self._profile_state(), before_profiles)

    def test_login_intent_cannot_link_the_signed_in_account(self):
        """A login transaction never invokes explicit account linking"""
        before_profiles = self._profile_state()
        before_users = self._user_state()

        response = self._request_callback(
            {"code": self.authorization_code},
            intent="login",
            user_id=None,
        )

        self.assertEqual(response["Location"], reverse("account_settings"))
        self._assert_current_session_user(self.user)
        self.assertEqual(self._profile_state(), before_profiles)
        self.assertEqual(self._user_state(), before_users)
        self.assertNotIn(self.access_token, repr(dict(self.client.session)))

    def test_first_link_sets_only_verified_identity_fields(self):
        """A first link preserves legacy profile, user, and session data"""
        linked_at = timezone.now().replace(microsecond=0)
        before_users = self._user_state()
        other_before = self._profile_state()[1]

        with patch("apps.pages.orcid_auth.timezone.now", return_value=linked_at):
            response = self._complete_link()

        self.profile.refresh_from_db()
        self._assert_link_succeeded(response)
        self.assertEqual(self.profile.authenticated_orcid, self.primary_orcid)
        self.assertEqual(self.profile.orcid_authenticated_at, linked_at)
        self.assertEqual(self.profile.orcid, "legacy-current-orcid")
        self.assertEqual(self.profile.institution, "Current Institute")
        self.assertEqual(self._profile_state()[1], other_before)
        self.assertEqual(self._user_state(), before_users)
        self._assert_current_session_user(self.user)

    def test_link_creates_a_missing_profile_without_changing_the_user(self):
        """A missing current profile is safely created during first link"""
        self.profile.delete()
        before_users = self._user_state()
        other_before = self._profile_state()[0]

        response = self._complete_link()

        created_profile = AccountProfile.objects.get(user=self.user)
        self._assert_link_succeeded(response)
        self.assertEqual(created_profile.authenticated_orcid, self.primary_orcid)
        self.assertIsNotNone(created_profile.orcid_authenticated_at)
        self.assertEqual(created_profile.orcid, "")
        self.assertEqual(created_profile.institution, "")
        self.assertEqual(
            AccountProfile.objects.values(
                "user_id",
                "institution",
                "orcid",
                "authenticated_orcid",
                "orcid_authenticated_at",
            ).get(user=self.other),
            other_before,
        )
        self.assertEqual(self._user_state(), before_users)
        self._assert_current_session_user(self.user)

    def test_link_integrity_race_is_controlled_without_partial_mutation(self):
        """A final uniqueness conflict returns safely with no partial link"""
        before_profiles = self._profile_state()
        before_users = self._user_state()

        with patch.object(
            AccountProfile,
            "save",
            side_effect=IntegrityError("private concurrent identity conflict"),
        ):
            response = self._complete_link()

        artifacts = self._assert_link_refused(response)
        self._assert_current_session_user(self.user)
        self.assertEqual(self._profile_state(), before_profiles)
        self.assertEqual(self._user_state(), before_users)
        self.assertNotIn(
            "private concurrent identity conflict",
            artifacts,
        )


@override_settings(
    ORCID_CLIENT_ID="APP-TEST",
    ORCID_CLIENT_SECRET="private-client-secret",
    ORCID_REDIRECT_URI="https://pilot.example/settings/orcid/callback/",
)
class ORCIDCallbackFailureTests(ORCIDCallbackTestMixin, TestCase):
    """
    Test callback rejection, privacy, and intent boundaries
    """

    def _assert_login_failure_without_mutation(self, response):
        """
        Assert a callback failed safely before local identity mutation

        Parameters
        ----------
        response : HttpResponse
            Callback response to inspect.
        """
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], settings.LOGIN_URL)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(AccountProfile.objects.count(), 0)

    def test_missing_transaction_is_rejected_before_exchange(self):
        """
        A callback without a stored transaction never reaches ORCID
        """
        response = self.client.get(
            reverse("orcid_callback"),
            {"state": "callback-state", "code": self.authorization_code},
        )

        self._assert_login_failure_without_mutation(response)
        self.exchange.assert_not_called()

    def test_missing_state_consumes_transaction_before_exchange(self):
        """
        A missing callback state consumes and rejects the transaction
        """
        response = self._request_callback(
            {"code": self.authorization_code},
            include_state=False,
        )

        self._assert_login_failure_without_mutation(response)
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        self.exchange.assert_not_called()

    def test_malformed_state_consumes_transaction_before_exchange(self):
        """
        Malformed returned state is rejected before provider exchange
        """
        self._store_transaction()

        response = self.client.get(
            reverse("orcid_callback"),
            {"state": "callback-stäte", "code": self.authorization_code},
        )

        self._assert_login_failure_without_mutation(response)
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        self.exchange.assert_not_called()

    def test_state_mismatch_consumes_transaction_before_exchange(self):
        """
        A mismatched callback state cannot exchange an authorization code
        """
        self._store_transaction()

        response = self.client.get(
            reverse("orcid_callback"),
            {"state": "other-state", "code": self.authorization_code},
        )

        self._assert_login_failure_without_mutation(response)
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        self.exchange.assert_not_called()

    def test_consumed_transaction_cannot_be_replayed(self):
        """
        A successful callback state cannot authorize a second callback
        """
        completed_user = User.objects.create_user(
            username="completed-replay-user", password="local-password"
        )
        AccountProfile.objects.create(
            user=completed_user,
            authenticated_orcid=self.primary_orcid,
            orcid_authenticated_at=timezone.now(),
        )
        first_response = self._complete_login()
        first_user = AccountProfile.objects.get(
            authenticated_orcid=self.primary_orcid
        ).user
        self.assertEqual(first_response["Location"], "/search/")
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        self.exchange.reset_mock()

        replay_response = self.client.get(
            reverse("orcid_callback"),
            {
                "state": "callback-state",
                "code": "second-private-code",
            },
        )

        self.assertEqual(replay_response["Location"], settings.LOGIN_URL)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            first_user.pk,
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(
            AccountProfile.objects.get().user_id,
            first_user.pk,
        )
        self.exchange.assert_not_called()

    def test_expired_transaction_is_rejected_before_exchange(self):
        """
        An expired callback transaction never reaches the provider
        """
        expired_at = (timezone.now() - timedelta(seconds=601)).timestamp()

        response = self._request_callback(
            {"code": self.authorization_code},
            created_at=expired_at,
        )

        self._assert_login_failure_without_mutation(response)
        self.exchange.assert_not_called()

    def test_access_denial_cancels_without_exchange_or_secret_echo(self):
        """
        Provider access denial returns a fixed local cancellation
        """
        provider_description = "private provider denial detail"

        response = self._request_callback(
            {
                "error": "access_denied",
                "error_description": provider_description,
                "code": self.authorization_code,
            }
        )

        self._assert_login_failure_without_mutation(response)
        self.exchange.assert_not_called()
        self._assert_sensitive_values_absent(
            response,
            self.authorization_code,
            settings.ORCID_CLIENT_SECRET,
            provider_description,
            "access_denied",
        )

    def test_other_provider_error_cancels_without_exchange(self):
        """
        Any provider error parameter cancels with the same fixed response
        """
        response = self._request_callback(
            {
                "error": "temporarily_unavailable",
                "error_description": "private provider outage detail",
            }
        )

        self._assert_login_failure_without_mutation(response)
        self.exchange.assert_not_called()
        artifacts = self._response_artifacts(response)
        self.assertNotIn("temporarily_unavailable", artifacts)
        self.assertNotIn("private provider outage detail", artifacts)

    def test_missing_and_blank_codes_never_reach_exchange(self):
        """
        A missing or blank authorization code is rejected locally
        """
        for query in ({}, {"code": ""}, {"code": "   "}):
            with self.subTest(query=query):
                response = self._request_callback(query)
                self._assert_login_failure_without_mutation(response)
                self.exchange.assert_not_called()

    def test_provider_exchange_failures_are_fixed_and_private(self):
        """
        Network and decoding exceptions return one safe local failure
        """
        failures = (
            HTTPError(
                "https://provider.example/private",
                502,
                "private HTTP detail",
                None,
                None,
            ),
            URLError("private URL detail"),
            TimeoutError("private timeout detail"),
            json.JSONDecodeError(
                "private JSON detail",
                "private provider body",
                0,
            ),
            UnicodeDecodeError(
                "utf-8",
                b"private provider bytes\xff",
                22,
                23,
                "private Unicode detail",
            ),
        )

        for failure in failures:
            with self.subTest(failure_type=type(failure).__name__):
                self.exchange.reset_mock()
                self.exchange.side_effect = failure
                response = self._request_callback(
                    {"code": self.authorization_code}
                )
                self._assert_login_failure_without_mutation(response)
                self.exchange.assert_called_once_with(
                    self.authorization_code,
                    "https://pilot.example/settings/orcid/callback/",
                )
                artifacts = self._assert_sensitive_values_absent(
                    response,
                    self.authorization_code,
                    settings.ORCID_CLIENT_SECRET,
                    self.access_token,
                )
                self.assertNotIn(str(failure), artifacts)

        self.exchange.side_effect = None

    def test_non_dict_provider_payloads_are_rejected(self):
        """
        Only a built-in JSON object may carry provider token data
        """
        invalid_payloads = (
            None,
            [],
            "provider response",
            UserDict(self._provider_payload()),
        )

        for payload in invalid_payloads:
            with self.subTest(payload_type=type(payload).__name__):
                self.exchange.return_value = payload
                response = self._request_callback(
                    {"code": self.authorization_code}
                )
                self._assert_login_failure_without_mutation(response)

    def test_missing_blank_and_nonstring_access_tokens_are_rejected(self):
        """
        Provider data requires a nonempty string access token
        """
        invalid_tokens = (None, "", "   ", 123, ["provider-token"])

        for token in invalid_tokens:
            with self.subTest(token=token):
                payload = self._provider_payload(access_token=token)
                if token is None:
                    payload.pop("access_token")
                self.exchange.return_value = payload
                response = self._request_callback(
                    {"code": self.authorization_code}
                )
                self._assert_login_failure_without_mutation(response)

    def test_missing_and_invalid_orcid_values_are_rejected(self):
        """
        Provider data requires one canonical checksum-valid ORCID iD
        """
        invalid_orcids = (
            None,
            "",
            "   ",
            "0000-0002-1451-2716",
            "https://orcid.org/0000-0002-1451-2715",
            214512715,
        )

        for orcid in invalid_orcids:
            with self.subTest(orcid=orcid):
                payload = self._provider_payload(orcid=orcid)
                if orcid is None:
                    payload.pop("orcid")
                self.exchange.return_value = payload
                response = self._request_callback(
                    {"code": self.authorization_code}
                )
                self._assert_login_failure_without_mutation(response)

    def test_tampered_intent_is_rejected_before_exchange(self):
        """
        An unknown stored intent is consumed before provider exchange
        """
        response = self._request_callback(
            {"code": self.authorization_code},
            intent="delete",
        )

        self._assert_login_failure_without_mutation(response)
        self.exchange.assert_not_called()
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)

    def test_callback_accepts_get_only(self):
        """
        POST cannot consume a callback transaction or exchange a code
        """
        self._store_transaction()

        response = self.client.post(
            reverse("orcid_callback"),
            {"state": "callback-state", "code": self.authorization_code},
        )

        self.assertEqual(response.status_code, 405)
        self.assertIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        self.exchange.assert_not_called()


@override_settings(
    ORCID_CLIENT_ID="APP-TEST",
    ORCID_CLIENT_SECRET="super-secret-value",
    ORCID_BASE_URL="https://sandbox.orcid.org",
)
class ORCIDRememberSessionTests(ORCIDCallbackTestMixin, TestCase):
    """
    Exercise session persistence through real ORCID start and callback views
    """

    def test_start_accepts_only_the_checked_checkbox_value(self):
        """
        Record an explicit checkbox choice without accepting truthy strings
        """
        for submitted, expected in ((None, False), ("on", True), ("false", False), ("1", False)):
            with self.subTest(submitted=submitted):
                query = {} if submitted is None else {"remember_me": submitted}
                response = self.client.get(reverse("orcid_login"), query)

                self.assertEqual(response.status_code, 302)
                self.assertIs(
                    self.client.session[ORCID_TRANSACTION_SESSION_KEY].get("remember_me"),
                    expected,
                )

    def test_callback_uses_stored_choice_and_the_initial_login_deadline(self):
        """
        Ignore callback persistence values and apply the original login choice
        """
        user = User.objects.create_user(username="remembered-orcid", password="password")
        AccountProfile.objects.create(user=user, authenticated_orcid=self.primary_orcid)
        now = timezone.now()

        for remember_me, lifetime in ((False, 30 * 24 * 60 * 60), (True, 365 * 24 * 60 * 60)):
            with self.subTest(remember_me=remember_me):
                self.client.logout()
                with patch("apps.pages.orcid_auth.timezone.now", return_value=now):
                    self.client.get(
                        reverse("orcid_login"),
                        {"remember_me": "on" if remember_me else ""},
                    )
                    state = self.client.session[ORCID_TRANSACTION_SESSION_KEY]["state"]
                    response = self.client.get(
                        reverse("orcid_callback"),
                        {
                            "state": state,
                            "code": self.authorization_code,
                            "remember_me": "" if remember_me else "on",
                        },
                    )

                self.assertEqual(response["Location"], "/search/")
                session = self.client.session
                self.assertEqual(session["_auth_user_id"], str(user.pk))
                self.assertEqual(session.get("login_expires_at"), now.timestamp() + lifetime)
                self.assertIs(session.get("login_remember_me"), remember_me)
                self.assertFalse(session.get_expire_at_browser_close())
                cookie = response.cookies[settings.SESSION_COOKIE_NAME]
                self.assertTrue(cookie["max-age"])
                self.assertTrue(cookie["expires"])

    def test_only_remembered_orcid_sessions_renew_on_later_visits(self):
        """
        Renew remembered ORCID sessions without extending ordinary login sessions

        A normal page visit two days later exercises the shared policy using
        the choice stored by the real authorization start and callback views.
        """
        user = User.objects.create_user(username="returning-orcid", password="password")
        AccountProfile.objects.create(user=user, authenticated_orcid=self.primary_orcid)
        now = timezone.now()

        for remember_me, expected_days in ((False, 30), (True, 367)):
            with self.subTest(remember_me=remember_me):
                self.client.logout()
                with patch("apps.pages.orcid_auth.timezone.now", return_value=now):
                    self.client.get(
                        reverse("orcid_login"),
                        {"remember_me": "on" if remember_me else ""},
                    )
                    state = self.client.session[ORCID_TRANSACTION_SESSION_KEY]["state"]
                    callback = self.client.get(
                        reverse("orcid_callback"),
                        {"state": state, "code": self.authorization_code},
                    )
                self.assertEqual(callback["Location"], "/search/")

                with patch(
                    "apps.pages.orcid_auth.timezone.now",
                    return_value=now + timedelta(days=2),
                ):
                    response = self.client.get(
                        reverse("search"),
                        HTTP_SEC_FETCH_DEST="document",
                        HTTP_SEC_FETCH_MODE="navigate",
                    )

                self.assertEqual(response.status_code, 200)
                session = self.client.session
                self.assertEqual(session["_auth_user_id"], str(user.pk))
                self.assertIs(session.get("login_remember_me"), remember_me)
                self.assertEqual(
                    session.get("login_expires_at"),
                    (now + timedelta(days=expected_days)).timestamp(),
                )
                self.assertFalse(session.get_expire_at_browser_close())

    def test_first_orcid_login_retains_persistence_during_required_setup(self):
        """
        Apply the remembered deadline before redirecting a new account to setup
        """
        now = timezone.now()
        with patch("apps.pages.orcid_auth.timezone.now", return_value=now):
            self.client.get(reverse("orcid_login"), {"remember_me": "on"})
            state = self.client.session[ORCID_TRANSACTION_SESSION_KEY]["state"]
            response = self.client.get(
                reverse("orcid_callback"),
                {"state": state, "code": self.authorization_code},
            )

        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(
            self.client.session.get("login_expires_at"),
            now.timestamp() + 365 * 24 * 60 * 60,
        )
        self.assertIs(self.client.session.get("login_remember_me"), True)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_authenticated_login_and_link_do_not_extend_existing_deadlines(self):
        """
        Preserve the current session when ORCID verifies an authenticated user
        """
        user = User.objects.create_user(username="signed-in-orcid", password="password")
        AccountProfile.objects.create(user=user, authenticated_orcid=self.primary_orcid)

        for route in ("orcid_login", "orcid_connect"):
            with self.subTest(route=route):
                self.client.force_login(user)
                session = self.client.session
                deadline = timezone.now() + timedelta(hours=2)
                session["login_expires_at"] = deadline.timestamp()
                session.set_expiry(0)
                session.save()

                self.client.get(reverse(route), {"remember_me": "on"})
                state = self.client.session[ORCID_TRANSACTION_SESSION_KEY]["state"]
                response = self.client.get(
                    reverse("orcid_callback"),
                    {"state": state, "code": self.authorization_code},
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.client.session["login_expires_at"], deadline.timestamp())
                self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_registration_auto_login_uses_an_unremembered_deadline(self):
        """
        Use an ordinary fixed session after registration even if remember is submitted
        """
        now = timezone.now()
        with patch("apps.pages.views.timezone.now", return_value=now):
            response = self.client.post(
                reverse("register"),
                {
                    "username": "new-unremembered-user",
                    "password1": "Sample!StrongPass924",
                    "password2": "Sample!StrongPass924",
                    "remember_me": "on",
                },
            )

        self.assertEqual(response["Location"], "/search/")
        self.assertEqual(self.client.session.get("login_expires_at"), now.timestamp() + 30 * 24 * 60 * 60)
        self.assertIs(self.client.session.get("login_remember_me"), False)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
