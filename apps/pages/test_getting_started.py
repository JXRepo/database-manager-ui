from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class GettingStartedTests(TestCase):
    """
    Keep the optional introduction tied to each account
    """

    def setUp(self):
        """
        Create an account without an existing profile or introduction state
        """
        self.user = User.objects.create_user(
            username="new-researcher", password="River!Quartz72Mosaic"
        )

    def test_password_login_offers_guide_without_changing_return_target(self):
        """
        Offer help on the requested page without consuming it during rendering
        """
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": "River!Quartz72Mosaic",
                "next": "/upload/",
            },
            follow=True,
        )

        self.assertEqual(response.redirect_chain, [("/upload/", 302)])
        self.assertIs(response.context.get("show_getting_started"), True)
        self.assertContains(response, 'id="quick-start-dialog"')
        self.assertFalse(AccountProfile.objects.filter(user=self.user).exists())

    def test_registration_offers_the_guide(self):
        """
        Include newly registered accounts even though registration signs them in
        """
        response = self.client.post(
            reverse("register"),
            {
                "username": "just-registered",
                "password1": "Forest!Bridge83Copper",
                "password2": "Forest!Bridge83Copper",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("search"))
        self.assertIs(response.context.get("show_getting_started"), True)

    def test_acknowledgement_persists_across_sessions_and_only_for_current_user(self):
        """
        Remember skipping or finishing without modifying another account
        """
        other = User.objects.create_user(username="other-researcher", password="pass")
        self.client.force_login(self.user)
        response = self.client.post(
            "/getting-started/",
            {"user_id": other.pk, "next": "/upload/"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"dismissed": True})
        dismissed_at = AccountProfile.objects.get(user=self.user).getting_started_dismissed_at
        self.assertIsNotNone(dismissed_at)
        self.assertFalse(AccountProfile.objects.filter(user=other).exists())

        another_browser = Client()
        another_browser.force_login(self.user)
        response = another_browser.get(reverse("search"))
        self.assertIs(response.context.get("show_getting_started"), False)
        self.assertContains(response, 'href="/getting-started/"')

        another_browser.post("/getting-started/")
        self.assertEqual(
            AccountProfile.objects.get(user=self.user).getting_started_dismissed_at,
            dismissed_at,
        )
        another_browser.force_login(other)
        response = another_browser.get(reverse("search"))
        self.assertIs(response.context.get("show_getting_started"), True)

    def test_manual_help_does_not_reset_or_consume_the_introduction(self):
        """
        Keep help available before and after acknowledgement without auto opening
        """
        self.client.force_login(self.user)
        for dismissed_at in (None, timezone.now()):
            with self.subTest(dismissed=bool(dismissed_at)):
                profile, _ = AccountProfile.objects.update_or_create(
                    user=self.user,
                    defaults={"getting_started_dismissed_at": dismissed_at},
                )
                response = self.client.get("/getting-started/")
                self.assertEqual(response.status_code, 200)
                self.assertIs(response.context.get("show_getting_started"), False)
                self.assertContains(response, 'data-guide-launch')
                self.assertContains(response, 'data-tour-target="share"')
                profile.refresh_from_db()
                self.assertEqual(profile.getting_started_dismissed_at, dismissed_at)

    def test_normal_form_submission_preserves_safe_local_targets(self):
        """
        Support navigation without JavaScript while rejecting external redirects
        """
        self.client.force_login(self.user)
        for target, expected in (
            ("/upload/", "/upload/"),
            ("/search/?q=copper&advanced=1", "/search/?q=copper&advanced=1"),
            ("https://outside.example/", "/search/"),
            ("//outside.example/", "/search/"),
            ("/\\outside.example/", "/search/"),
            ("javascript:alert(1)", "/search/"),
            ("", "/search/"),
        ):
            with self.subTest(target=target):
                response = self.client.post("/getting-started/", {"next": target})
                self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_anonymous_pages_do_not_show_guide_or_accept_acknowledgement(self):
        """
        Limit the introduction and its saved preference to signed in accounts
        """
        for url in (reverse("index"), reverse("login"), reverse("register")):
            response = self.client.get(url)
            self.assertNotContains(response, 'id="quick-start-dialog"')
        for method in (self.client.get, self.client.post):
            response = method("/getting-started/")
            self.assertRedirects(
                response, "/login/?next=/getting-started/", fetch_redirect_response=False
            )
        self.assertFalse(AccountProfile.objects.exists())

    def test_acknowledgement_requires_csrf_and_preserves_profile_fields(self):
        """
        Reject forged submissions and retain research profile information
        """
        profile = AccountProfile.objects.create(user=self.user, institution="Test lab")
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        response = browser.post("/getting-started/")
        self.assertEqual(response.status_code, 403)
        response = browser.get(reverse("search"))
        self.assertEqual(response.status_code, 200)
        response = browser.post(
            "/getting-started/",
            {"csrfmiddlewaretoken": browser.cookies["csrftoken"].value},
        )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.institution, "Test lab")
        self.assertIsNotNone(profile.getting_started_dismissed_at)

    def test_orcid_setup_finishes_before_the_optional_guide(self):
        """
        Defer help until required credentials are saved on the same ORCID account
        """
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        profile = AccountProfile.objects.create(
            user=self.user,
            authenticated_orcid="0000-0002-1451-2715",
            orcid_authenticated_at=timezone.now(),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("search"), follow=True)
        self.assertNotContains(response, 'id="quick-start-dialog"')
        self.assertContains(response, 'id="orcidSetupModal"')
        response = self.client.post("/getting-started/")
        self.assertRedirects(
            response, "/settings/orcid/setup/?next=%2Fsearch%2F",
            fetch_redirect_response=False,
        )
        response = self.client.post(
            reverse("orcid_setup_credentials"),
            {
                "orcid": profile.authenticated_orcid,
                "orcid_setup-username": "ready-researcher",
                "orcid_setup-password1": "River!Quartz72Mosaic",
                "orcid_setup-password2": "River!Quartz72Mosaic",
                "next": "/upload/",
            },
            follow=True,
        )
        self.assertRedirects(response, "/upload/")
        self.assertIs(response.context.get("show_getting_started"), True)
