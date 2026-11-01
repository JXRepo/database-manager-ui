import re
from smtplib import SMTPRecipientsRefused
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.mail import EmailMessage, get_connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import JSONData, RateLimitBucket


@override_settings(
    DEBUG=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Materials Platform <accounts@example.org>",
    PASSWORD_RESET_BASE_URL="https://materials.example.org",
    PASSWORD_RESET_TIMEOUT=3600,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class PasswordRecoveryTests(TestCase):
    """
    Verify recovery through the actual forms, email tokens and account sessions
    """

    def setUp(self):
        """
        Create an ordinary account and an existing authenticated browser
        """
        self.user = User.objects.create_user(
            username="recovery-researcher", email="researcher@example.org",
            password="OriginalQuartz!47River",
        )
        self.old_browser = Client()
        self.old_browser.force_login(self.user)
        self.obj = JSONData.objects.create(owner=self.user, data={"title": "Keep this data"})

    def request_link(self):
        """
        Submit a real recovery request and extract its isolated test email URL

        Returns
        -------
        str
            Confirmation path from the last message in Django's test outbox.
        """
        response = self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertTrue(mail.outbox)
        match = re.search(r"https://materials\.example\.org(\S+)", mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_login_links_and_recovery_page_are_available(self):
        """
        Make the previously inert login label open the recovery form
        """
        for path in ("/login/", "/accounts/login/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, f'href="{reverse("password_reset")}"')
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_reset_changes_password_and_invalidates_old_access_and_token(self):
        """
        Complete recovery without signing in automatically or changing data
        """
        path = self.request_link()
        response = self.client.get(path, follow=True)
        self.assertTrue(response.context["validlink"])
        safe_path = response.redirect_chain[-1][0]
        self.assertIn("/set-password/", safe_path)
        new_password = "Copper!Meadow58Orchard"
        response = self.client.post(safe_path, {
            "new_password1": new_password, "new_password2": new_password,
        }, follow=True)
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertContains(response, f'href="{reverse("login")}"')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(self.user.check_password("OriginalQuartz!47River"))
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.owner_id, self.user.pk)
        self.assertEqual(self.obj.data, {"title": "Keep this data"})
        self.assertEqual(self.old_browser.get(reverse("json_data_list")).status_code, 302)
        self.assertNotIn(SESSION_KEY, self.old_browser.session)
        self.assertFalse(self.client.get(path).context["validlink"])
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": "OriginalQuartz!47River",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": new_password,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_unknown_inactive_and_unusable_accounts_receive_the_same_page(self):
        """
        Avoid revealing account eligibility or sending to ineligible accounts
        """
        User.objects.create_user("disabled", email="disabled@example.org",
                                 password="LocalPass!47", is_active=False)
        User.objects.create_user("orcid-only", email="orcid@example.org")
        expected = self.client.post(reverse("password_reset"), {
            "email": self.user.email,
        }, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        for email in ("missing@example.org", "disabled@example.org", "orcid@example.org"):
            with self.subTest(email=email):
                response = self.client.post(reverse("password_reset"), {"email": email}, follow=True)
                self.assertEqual(response.status_code, expected.status_code)
                self.assertEqual(response.content, expected.content)
                self.assertEqual(len(mail.outbox), 1)

    def test_shared_email_can_recover_each_account_without_merging_them(self):
        """
        Keep separate accounts and tokens when their saved email is the same
        """
        other = User.objects.create_user("another-researcher", email=self.user.email,
                                         password="AnotherQuartz!56River")
        response = self.client.post(reverse("password_reset"), {
            "email": "  RESEARCHER@EXAMPLE.ORG  ",
        })
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotEqual(mail.outbox[0].body, mail.outbox[1].body)
        self.assertTrue(User.objects.filter(pk=other.pk, username=other.username).exists())

    def test_password_validation_keeps_the_token_and_original_password(self):
        """
        Reject weak or mismatched replacements without consuming the link
        """
        response = self.client.get(self.request_link(), follow=True)
        path = response.redirect_chain[-1][0]
        original = self.user.password
        for first, second in (("short", "short"), ("123456789012", "123456789012"),
                              ("Copper!Meadow58", "Different!Meadow59")):
            with self.subTest(password_kind=len(first)):
                response = self.client.post(path, {"new_password1": first, "new_password2": second})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertTrue(response.context["validlink"])
                self.user.refresh_from_db()
                self.assertEqual(self.user.password, original)

    def test_expired_and_malformed_links_cannot_change_the_password(self):
        """
        Offer a new request after expired or invalid token visits
        """
        path = self.request_link()
        future = default_token_generator._now() + timedelta(seconds=3601)
        with patch.object(default_token_generator, "_now", return_value=future):
            response = self.client.get(path, follow=True)
        self.assertFalse(response.context["validlink"])
        self.assertContains(response, f'href="{reverse("password_reset")}"')
        response = self.client.post("/accounts/password-reset-confirm/not-a-user/not-a-token/", {
            "new_password1": "Copper!Meadow58", "new_password2": "Copper!Meadow58",
        })
        self.assertFalse(response.context["validlink"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalQuartz!47River"))

    def test_inactive_account_cannot_use_a_previously_issued_link(self):
        """
        Check current account eligibility again when the reset link is opened
        """
        path = self.request_link()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertFalse(self.client.get(path, follow=True).context["validlink"])

    def test_csrf_protects_request_and_password_submission(self):
        """
        Reject cross site submissions at both mutation endpoints
        """
        browser = Client(enforce_csrf_checks=True)
        response = browser.post(reverse("password_reset"), {"email": self.user.email})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        response = browser.get(self.request_link(), follow=True)
        path = response.redirect_chain[-1][0]
        response = browser.post(path, {
            "new_password1": "Copper!Meadow58", "new_password2": "Copper!Meadow58",
        })
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalQuartz!47River"))

    def test_request_host_does_not_replace_the_configured_email_origin(self):
        """
        Build the emailed URL from the configured origin rather than the visitor host
        """
        with override_settings(ALLOWED_HOSTS=["untrusted.example.org"]):
            response = self.client.post(reverse("password_reset"), {
                "email": self.user.email,
            }, HTTP_HOST="untrusted.example.org")
        self.assertEqual(response.status_code, 302)
        self.assertIn("https://materials.example.org/accounts/password-reset-confirm/", mail.outbox[0].body)
        self.assertNotIn("untrusted.example.org", mail.outbox[0].body)

    def test_request_limit_blocks_further_sends_from_the_same_address(self):
        """
        Apply the persisted IP quota before sending recovery messages
        """
        limits = {**settings.PILOT_RATE_LIMITS, "password_reset": {"limit": 1, "window_seconds": 900}}
        with override_settings(PILOT_RATE_LIMITS=limits):
            self.request_link()
            response = self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_saved_email_change_invalidates_an_existing_reset_link(self):
        """
        Stop an old inbox from resetting an account after its email changes
        """
        path = self.request_link()
        self.user.email = "updated@example.org"
        self.user.save(update_fields=["email"])
        self.assertFalse(self.client.get(path, follow=True).context["validlink"])

    def test_invalid_email_does_not_send_a_message(self):
        """
        Keep malformed input on the form with a field error
        """
        response = self.client.post(reverse("password_reset"), {"email": "not-an-email"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DEBUG=False, EMAIL_BACKEND="apps.pages.email_backend.ResendEmailBackend",
                       RESEND_API_KEY="private-provider-key")
    def test_delivery_failure_keeps_the_same_acknowledgement_and_password(self):
        """
        Keep provider failures out of account lookup responses and public logs
        """
        response = Mock(status_code=403)
        with patch("apps.pages.email_backend.requests.post", return_value=response):
            with self.assertLogs("django.contrib.auth", level="ERROR") as logs:
                known = self.client.post(reverse("password_reset"), {"email": self.user.email}, follow=True)
        unknown = self.client.post(reverse("password_reset"), {"email": "missing@example.org"}, follow=True)
        self.assertEqual(known.content, unknown.content)
        self.assertNotIn("private-provider-key", "\n".join(logs.output))
        self.assertNotIn(self.user.email, "\n".join(logs.output))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalQuartz!47River"))

    def test_destination_quota_covers_requests_from_different_ips(self):
        """
        Limit repeated messages to one inbox without exposing its eligibility
        """
        limits = {**settings.PILOT_RATE_LIMITS, "password_reset_email": {"limit": 1, "window_seconds": 3600}}
        with override_settings(PILOT_RATE_LIMITS=limits):
            self.request_link()
            response = self.client.post(reverse("password_reset"), {
                "email": self.user.email.upper(),
            }, REMOTE_ADDR="192.0.2.10")
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(RateLimitBucket.objects.filter(identifier_hash__contains="researcher").exists())

    @override_settings(DEBUG=False, EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                       EMAIL_HOST="smtp.example.org", EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
    def test_smtp_failure_keeps_recipient_and_diagnostics_out_of_logs(self):
        """
        Sanitize SMTP errors while preserving the neutral request response
        """
        smtp = Mock()
        smtp.sendmail.side_effect = SMTPRecipientsRefused({
            self.user.email: (550, b"private-provider-diagnostic"),
        })
        with patch("django.core.mail.backends.smtp.smtplib.SMTP", return_value=smtp):
            with self.assertLogs("django.contrib.auth", level="ERROR") as logs:
                known = self.client.post(reverse("password_reset"), {"email": self.user.email}, follow=True)
        smtp.sendmail.assert_called_once()
        unknown = self.client.post(reverse("password_reset"), {"email": "missing@example.org"}, follow=True)
        self.assertEqual(known.content, unknown.content)
        self.assertNotIn(self.user.email, "\n".join(logs.output))
        self.assertNotIn("private-provider-diagnostic", "\n".join(logs.output))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalQuartz!47River"))

    @override_settings(DEBUG=False, EMAIL_BACKEND="apps.pages.email_backend.ResendEmailBackend", RESEND_API_KEY="")
    def test_missing_delivery_configuration_is_visible_before_account_lookup(self):
        """
        Report unavailable email instead of pretending to send a recovery link
        """
        response = self.client.get(reverse("password_reset"))
        self.assertContains(response, "temporarily unavailable")
        for email in (self.user.email, "missing@example.org"):
            response = self.client.post(reverse("password_reset"), {"email": email})
            self.assertEqual(response.status_code, 503)
            self.assertContains(response, "temporarily unavailable", status_code=503)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DEBUG=False, EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_production_console_backend_cannot_expose_recovery_tokens(self):
        """
        Refuse production recovery when messages would only be written to logs
        """
        with patch("sys.stdout.write") as output:
            response = self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertEqual(response.status_code, 503)
        output.assert_not_called()


@override_settings(RESEND_API_KEY="test-provider-key", EMAIL_TIMEOUT=10)
class RecoveryMailBackendTests(SimpleTestCase):
    """
    Check the HTTPS provider boundary without sending real email
    """

    def message(self):
        """
        Build a plain text reset message for the configured provider backend

        Returns
        -------
        EmailMessage
            Isolated example email with a provider connection.
        """
        connection = get_connection("apps.pages.email_backend.ResendEmailBackend")
        return EmailMessage("Reset your password", "A private reset link", "accounts@example.org",
                            ["researcher@example.org"], connection=connection)

    def test_https_transport_sends_the_message_with_bounded_timeout(self):
        """
        Send the intended payload to Resend without following redirects
        """
        response = Mock(status_code=200)
        response.json.return_value = {"id": "accepted-message"}
        with patch("apps.pages.email_backend.requests.post", return_value=response) as post:
            self.assertEqual(self.message().send(), 1)
        self.assertEqual(post.call_args.args, ("https://api.resend.com/emails",))
        self.assertEqual(post.call_args.kwargs["json"], {
            "from": "accounts@example.org", "to": ["researcher@example.org"],
            "subject": "Reset your password", "text": "A private reset link",
        })
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-provider-key")
        self.assertEqual(post.call_args.kwargs["timeout"], 10)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_provider_failures_do_not_expose_response_or_request_secrets(self):
        """
        Replace transport details with a safe delivery error
        """
        with patch("apps.pages.email_backend.requests.post", side_effect=requests.RequestException("private reset link")):
            with self.assertRaises(Exception) as caught:
                self.message().send()
        self.assertNotIn("private reset link", str(caught.exception))
        self.assertNotIn("test-provider-key", str(caught.exception))

    def test_redirect_is_not_accepted_as_successful_delivery(self):
        """
        Reject redirect responses without forwarding the API credential
        """
        with patch("apps.pages.email_backend.requests.post", return_value=Mock(status_code=302)):
            with self.assertRaises(Exception):
                self.message().send()


@override_settings(DEBUG=False, EMAIL_BACKEND="apps.pages.email_backend.ResendEmailBackend",
                   DEFAULT_FROM_EMAIL="accounts@example.org", RESEND_API_KEY="test-provider-key")
class RecoveryConfigurationTests(SimpleTestCase):
    """
    Reject unsafe or unusable canonical origins before accepting recovery requests
    """

    def test_production_requires_a_valid_https_origin(self):
        """
        Prevent malformed origins or development origins from entering reset mail
        """
        from .password_reset import password_reset_email_available

        for origin in ("", "http://materials.example.org", "https://user:pass@materials.example.org",
                       "https://materials.example.org/path", "https://materials.example.org?query=1",
                       "https://materials.example.org#fragment", "https://materials.example.org:invalid"):
            with self.subTest(origin=origin), override_settings(PASSWORD_RESET_BASE_URL=origin):
                self.assertFalse(password_reset_email_available())
        with override_settings(PASSWORD_RESET_BASE_URL="https://materials.example.org"):
            self.assertTrue(password_reset_email_available())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                       EMAIL_HOST="smtp.example.org",
                       PASSWORD_RESET_BASE_URL="https://materials.example.org")
    def test_production_smtp_requires_exactly_one_encrypted_mode(self):
        """
        Reject plaintext or conflicting SMTP transport modes in production
        """
        from .password_reset import password_reset_email_available

        for tls, ssl, expected in ((False, False, False), (True, True, False),
                                   (True, False, True), (False, True, True)):
            with self.subTest(tls=tls, ssl=ssl), override_settings(EMAIL_USE_TLS=tls, EMAIL_USE_SSL=ssl):
                self.assertEqual(password_reset_email_available(), expected)
