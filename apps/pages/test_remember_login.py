from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RememberLoginTests(TestCase):
    """
    Cover the remember choice on both password login routes
    """

    def setUp(self):
        """
        Create a user who can authenticate through the real login form
        """
        self.user = User.objects.create_user(
            username="remember-user",
            password="LocalLoginPassword!42",
        )

    def test_login_renders_one_unchecked_remember_field(self):
        """
        Offer an optional unchecked choice linked to its visible label
        """
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("remember_me", form.fields)
        self.assertFalse(form.fields["remember_me"].required)
        self.assertFalse(form["remember_me"].value())
        self.assertContains(response, 'name="remember_me"', count=1)
        self.assertContains(response, str(form["remember_me"]), html=True)
        self.assertContains(response, 'for="id_remember_me"')

    def test_invalid_login_preserves_the_checked_choice(self):
        """
        Keep the remember choice available after a password error
        """
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong", "remember_me": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("remember_me", response.context["form"].fields)
        self.assertTrue(response.context["form"]["remember_me"].value())
        self.assertContains(response, str(response.context["form"]["remember_me"]), html=True)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_omitted_choice_uses_a_persistent_thirty_day_cookie(self):
        """
        Keep both password logins across browser restarts for thirty days
        """
        now = datetime.now(datetime_timezone.utc)
        for login_url in ("/login/", "/accounts/login/"):
            with self.subTest(login_url=login_url):
                self.client.logout()
                with patch("django.utils.timezone.now", return_value=now):
                    response = self.client.post(
                        login_url,
                        {"username": self.user.username, "password": "LocalLoginPassword!42"},
                    )

                self.assertEqual(response.status_code, 302)
                session = self.client.session
                self.assertEqual(session["_auth_user_id"], str(self.user.pk))
                self.assertIs(session.get("login_remember_me"), False)
                self.assertFalse(session.get_expire_at_browser_close())
                self.assertEqual(
                    session.get("login_expires_at"),
                    (now + timedelta(days=30)).timestamp(),
                )
                self.assertEqual(session.get_expiry_date(), now + timedelta(days=30))
                cookie = response.cookies[settings.SESSION_COOKIE_NAME]
                self.assertEqual(int(cookie["max-age"]), 2592000)
                self.assertTrue(cookie["expires"])

    def test_checked_choice_starts_a_persistent_year_of_remembered_login(self):
        """
        Start a remembered login with a persistent cookie lasting one year
        """
        now = datetime.now(datetime_timezone.utc)
        for login_url in ("/login/", "/accounts/login/"):
            with self.subTest(login_url=login_url):
                self.client.logout()
                with patch("django.utils.timezone.now", return_value=now):
                    response = self.client.post(
                        login_url,
                        {
                            "username": self.user.username,
                            "password": "LocalLoginPassword!42",
                            "remember_me": "on",
                        },
                    )

                self.assertEqual(response.status_code, 302)
                session = self.client.session
                self.assertIs(session.get("login_remember_me"), True)
                self.assertFalse(session.get_expire_at_browser_close())
                self.assertEqual(
                    session.get("login_expires_at"),
                    (now + timedelta(days=365)).timestamp(),
                )
                self.assertEqual(session.get_expiry_date(), now + timedelta(days=365))
                self.assertEqual(
                    int(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"]),
                    31536000,
                )

    def test_false_choice_does_not_enable_remembering(self):
        """
        Honor the form's boolean parsing instead of truthy POST strings
        """
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": "LocalLoginPassword!42",
                "remember_me": "false",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIs(self.client.session.get("login_remember_me"), False)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertAlmostEqual(self.client.session.get_expiry_age(), 2592000, delta=5)

    def test_failed_login_does_not_replace_an_existing_expiry(self):
        """
        Leave an existing authenticated session unchanged on failed login
        """
        self.client.force_login(self.user)
        session = self.client.session
        expires_at = datetime.now(datetime_timezone.utc) + timedelta(days=2)
        session.set_expiry(expires_at)
        session["login_expires_at"] = expires_at.timestamp()
        session["login_remember_me"] = False
        session.save()

        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get_expiry_date(), expires_at)

    def test_orcid_link_preserves_next_and_loads_choice_handler(self):
        """
        Retain the safe ORCID link and load the checkbox synchronization
        """
        response = self.client.get(reverse("login"), {"next": "/search/?q=steel"})

        self.assertContains(response, 'href="/login/orcid/?next=/search/%3Fq%3Dsteel"')
        self.assertContains(response, 'id="orcid-login-link"')
        self.assertContains(response, 'src="/static/assets/js/remember-login.js"')

    def test_admin_login_starts_the_short_lifetime_without_remembering(self):
        """
        Apply the short session policy immediately after a valid admin login
        """
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        now = datetime.now(datetime_timezone.utc)

        with patch("django.utils.timezone.now", return_value=now):
            response = self.client.post(
                "/admin/login/",
                {
                    "username": self.user.username,
                    "password": "LocalLoginPassword!42",
                    "remember_me": "on",
                    "next": "/admin/",
                },
            )

        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        self.assertIs(self.client.session.get("login_remember_me"), False)
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(
            self.client.session.get("login_expires_at"),
            (now + timedelta(hours=8)).timestamp(),
        )
