from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginSessionPolicyTests(TestCase):
    """
    Verify fixed and renewable logins independently of browser cookie deletion
    """

    def setUp(self):
        """
        Prepare an authenticated account without a preexisting policy
        """
        self.user = User.objects.create_user("session_researcher", password="Quartz!Mosaic72River")
        self.client.force_login(self.user)
        self.now = timezone.now()

    def apply_policy(self, remember_me=False):
        """
        Apply the login policy to the test client's session

        Parameters
        ----------
        remember_me : bool
            Whether the user chose a persistent login.

        Returns
        -------
        SessionStore
            Saved session containing the selected deadline.
        """
        from .session_policy import apply_login_session_policy

        request = RequestFactory().get("/login/")
        request.session = self.client.session
        with patch("django.utils.timezone.now", return_value=self.now):
            apply_login_session_policy(request, remember_me)
        request.session.save()
        return request.session

    def test_default_cookie_is_browser_length_and_eight_hours(self):
        """
        Keep all otherwise unconfigured sessions short by default
        """
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 60 * 60)

    def test_unremembered_policy_uses_persistent_cookie_and_fixed_deadline(self):
        """
        Retain an ordinary login for thirty days across browser restarts
        """
        session = self.apply_policy()
        deadline = self.now + timedelta(days=30)
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertIs(session["login_remember_me"], False)
        self.assertEqual(session["login_expires_at"], deadline.timestamp())
        self.assertEqual(session.get_expiry_date(), deadline)

    def test_remembered_policy_starts_with_a_persistent_year(self):
        """
        Start a renewable remembered login without a monthly expiry
        """
        session = self.apply_policy(True)
        deadline = self.now + timedelta(days=365)
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertIs(session["login_remember_me"], True)
        self.assertEqual(session["login_expires_at"], deadline.timestamp())
        self.assertEqual(session.get_expiry_date(), deadline)

    def test_existing_session_gets_default_policy_once(self):
        """
        Give sessions without policy metadata a fixed thirty day transition
        """
        with patch("django.utils.timezone.now", return_value=self.now):
            response = self.client.get(reverse("search"))
        self.assertEqual(response.status_code, 200)
        deadline = self.client.session["login_expires_at"]
        self.assertEqual(deadline, self.now.timestamp() + 30 * 24 * 60 * 60)
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(int(cookie["max-age"]), 30 * 24 * 60 * 60)
        self.assertTrue(cookie["expires"])
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(hours=1)):
            self.client.get(reverse("search"))
        self.assertEqual(self.client.session["login_expires_at"], deadline)

    def test_expiry_invalidates_session_before_protected_view(self):
        """
        Reject expired requests even when the browser still sends its cookie
        """
        for remembered, duration in ((False, timedelta(days=30)), (True, timedelta(days=365))):
            with self.subTest(remembered=remembered):
                self.client.force_login(self.user)
                self.apply_policy(remembered)
                # force the middleware to enforce its deadline independently of storage expiry
                session = self.client.session
                session.set_expiry(self.now + timedelta(days=730))
                session.save()
                old_key = self.client.session.session_key
                with patch("django.utils.timezone.now", return_value=self.now + duration):
                    response = self.client.get(reverse("search"))
                self.assertEqual(response.status_code, 302)
                self.assertIn(settings.LOGIN_URL, response.url)
                self.assertNotIn(SESSION_KEY, self.client.session)
                self.assertFalse(Session.objects.filter(session_key=old_key).exists())

    def test_polling_and_session_writes_cannot_extend_deadline(self):
        """
        Keep the original deadline across background reads and session writes
        """
        for remembered in (False, True):
            with self.subTest(remembered=remembered):
                self.client.force_login(self.user)
                session = self.apply_policy(remembered)
                deadline = session["login_expires_at"]
                expiry = session.get("_session_expiry")
                with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=2)):
                    self.client.get(reverse("search_live_data_objects"))
                    session = self.client.session
                    session["unrelated_setting"] = "changed"
                    session.save()
                self.assertEqual(self.client.session["login_expires_at"], deadline)
                self.assertEqual(self.client.session.get("_session_expiry"), expiry)

    def test_unremembered_visits_do_not_renew_the_thirty_day_limit(self):
        """
        Require login after thirty days even when the user visits regularly
        """
        session = self.apply_policy()
        deadline = session["login_expires_at"]
        for day in (2, 15, 29):
            with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=day)):
                self.assertEqual(self.client.get(reverse("search")).status_code, 200)
                self.assertEqual(self.client.session["login_expires_at"], deadline)

    def test_remembered_visits_renew_beyond_the_original_year(self):
        """
        Keep an active remembered user signed in past the first expiry
        """
        self.apply_policy(True)
        for day in (2, 300, 400):
            visit_time = self.now + timedelta(days=day)
            with patch("django.utils.timezone.now", return_value=visit_time):
                response = self.client.get(reverse("search"))
                session = self.client.session
                self.assertEqual(response.status_code, 200)
                self.assertEqual(session[SESSION_KEY], str(self.user.pk))
                self.assertEqual(session.get_expiry_date(), visit_time + timedelta(days=365))
                self.assertEqual(session["login_expires_at"], (visit_time + timedelta(days=365)).timestamp())
                self.assertEqual(int(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"]), 365 * 24 * 60 * 60)

    def test_remembered_renewal_is_limited_to_once_per_day(self):
        """
        Avoid writing the session on every ordinary page request
        """
        session = self.apply_policy(True)
        deadline = session["login_expires_at"]
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(hours=23)):
            response = self.client.get(reverse("search"))
            self.assertEqual(self.client.session["login_expires_at"], deadline)
            self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=1)):
            self.client.get(reverse("search"))
            self.assertEqual(self.client.session["login_expires_at"], deadline + 24 * 60 * 60)

    def test_only_successful_foreground_pages_renew_remembered_login(self):
        """
        Ignore polling, AJAX, failed pages, and invalid form submissions
        """
        session = self.apply_policy(True)
        deadline = session["login_expires_at"]
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=2)):
            self.client.get(reverse("search_live_data_objects"))
            self.client.get(reverse("search"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.client.get("/nonexistent-session-test-page/")
            self.client.post(reverse("password_change"), {"old_password": "wrong"})
            self.assertEqual(self.client.session["login_expires_at"], deadline)

    def test_reopened_browser_can_use_the_stored_login_cookie(self):
        """
        Retain both login modes when a new browser instance restores its cookie
        """
        for remember_me in (False, True):
            with self.subTest(remember_me=remember_me):
                self.apply_policy(remember_me)
                reopened = Client()
                reopened.cookies[settings.SESSION_COOKIE_NAME] = self.client.cookies[settings.SESSION_COOKIE_NAME].value
                with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=2)):
                    self.assertEqual(reopened.get(reverse("search")).status_code, 200)
                    self.assertEqual(reopened.session[SESSION_KEY], str(self.user.pk))

    def test_malformed_deadline_fails_closed(self):
        """
        Reject invalid existing metadata rather than granting extra time
        """
        for deadline in (None, True, "later", float("nan"), float("inf")):
            with self.subTest(deadline=deadline):
                self.client.force_login(self.user)
                session = self.client.session
                session["login_expires_at"] = deadline
                session.save()
                response = self.client.get(reverse("search"))
                self.assertEqual(response.status_code, 302)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_invalid_remember_metadata_cannot_enable_renewal(self):
        """
        Reject malformed stored choices instead of treating them as truthy
        """
        for value in ("on", "false", 1, None):
            with self.subTest(value=value):
                self.client.force_login(self.user)
                session = self.apply_policy()
                session["login_remember_me"] = value
                session.save()
                response = self.client.get(reverse("search"))
                self.assertEqual(response.status_code, 302)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_old_fixed_session_is_not_silently_opted_into_renewal(self):
        """
        Preserve an existing deadline when the old login has no remember flag
        """
        session = self.client.session
        deadline = self.now + timedelta(days=14)
        session["login_expires_at"] = deadline.timestamp()
        session.set_expiry(deadline)
        session.save()
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=7)):
            self.assertEqual(self.client.get(reverse("search")).status_code, 200)
            self.assertEqual(self.client.session["login_expires_at"], deadline.timestamp())
            self.assertNotIn("login_remember_me", self.client.session)

    def test_password_change_keeps_original_deadline(self):
        """
        Preserve remembered duration when Django rotates the session key
        """
        session = self.apply_policy(True)
        deadline = session["login_expires_at"]
        old_key = session.session_key
        response = self.client.post(reverse("password_change"), {
            "old_password": "Quartz!Mosaic72River",
            "new_password1": "Cobalt!Meadow83Cloud",
            "new_password2": "Cobalt!Meadow83Cloud",
        })
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session["login_expires_at"], deadline)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_expired_post_does_not_perform_action(self):
        """
        Stop protected state changes before processing submitted data
        """
        self.apply_policy()
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=30)):
            response = self.client.post(reverse("password_change"), {
                "old_password": "Quartz!Mosaic72River",
                "new_password1": "Cobalt!Meadow83Cloud",
                "new_password2": "Cobalt!Meadow83Cloud",
            })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Quartz!Mosaic72River"))

    def test_expiry_precedes_mandatory_orcid_setup(self):
        """
        Send expired unfinished accounts to login instead of onboarding
        """
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        AccountProfile.objects.create(
            user=self.user,
            authenticated_orcid="0000-0002-1451-2715",
            orcid_authenticated_at=self.now,
        )
        self.client.force_login(self.user)
        self.apply_policy()
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=30)):
            response = self.client.get(reverse("search"))
        self.assertIn(settings.LOGIN_URL, response.url)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_anonymous_visit_does_not_create_policy(self):
        """
        Leave public requests free of authenticated session metadata
        """
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("login_expires_at", self.client.session)

    def test_orcid_setup_preserves_remembered_deadline(self):
        """
        Retain the original expiry after setting initial local credentials
        """
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        AccountProfile.objects.create(
            user=self.user,
            authenticated_orcid="0000-0002-1451-2715",
            orcid_authenticated_at=self.now,
        )
        self.client.force_login(self.user)
        session = self.apply_policy(True)
        old_key = session.session_key
        deadline = session["login_expires_at"]
        response = self.client.post(reverse("orcid_setup_credentials"), {
            "orcid": "0000-0002-1451-2715",
            "orcid_setup-username": "chosen_researcher",
            "orcid_setup-password1": "Cobalt!Meadow83Cloud",
            "orcid_setup-password2": "Cobalt!Meadow83Cloud",
        })
        self.assertRedirects(response, reverse("search"))
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session["login_expires_at"], deadline)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_logout_revokes_remembered_session_immediately(self):
        """
        Remove both authentication and deadline on explicit logout
        """
        self.apply_policy(True)
        old_key = self.client.session.session_key
        self.client.post(reverse("logout"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn("login_expires_at", self.client.session)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
