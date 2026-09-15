from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import AccountSettingsForm
from .models import AccountProfile, JSONData
from .orcid_auth import ORCID_TRANSACTION_SESSION_KEY


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ORCIDDisconnectTests(TestCase):
    """
    Protect account access while disconnecting a verified ORCID identity
    """

    disconnect_url = "/settings/orcid/disconnect/"
    setup_url = "/settings/orcid/setup/"
    orcid = "0000-0002-1451-2715"

    def setUp(self):
        """
        Create a connected local account and one owned data record
        """
        self.user = User.objects.create_user(
            username="local-researcher",
            email="researcher@example.com",
            password="Quartz!Mosaic72River",
        )
        self.profile = AccountProfile.objects.create(
            user=self.user,
            institution="Research group",
            orcid="legacy-unverified-text",
            authenticated_orcid=self.orcid,
            orcid_authenticated_at=timezone.now(),
        )
        self.data = JSONData.objects.create(
            owner=self.user,
            data={"identifier": "disconnect-test-data"},
        )
        self.client.force_login(self.user)

    def _use_orcid_only_account(self):
        """
        Give the existing test account the credentials of an ORCID signup
        """
        self.user.username = "orcid_0000000214512715"
        self.user.set_unusable_password()
        self.user.save(update_fields=["username", "password"])
        self.client.force_login(self.user)

    def _setup_data(self, **overrides):
        """
        Build the credential setup payload submitted by the settings modal

        Parameters
        ----------
        **overrides : dict
            Explicit replacements for individual submitted fields.

        Returns
        -------
        dict
            Credential fields and the identity shown in the modal.
        """
        data = {
            "orcid": self.orcid,
            "orcid_setup-username": "chosen-researcher",
            "orcid_setup-password1": "Quartz!Mosaic72River",
            "orcid_setup-password2": "Quartz!Mosaic72River",
        }
        data.update(overrides)
        return data

    def test_connected_local_account_has_direct_disconnect_action(self):
        """
        Show verified state and a direct submit button without reauthentication
        """
        response = self.client.get(reverse("account_settings"))

        self.assertContains(response, "Connected")
        self.assertContains(response, self.orcid)
        self.assertContains(response, f'action="{self.disconnect_url}"')
        self.assertContains(response, 'form="orcid-disconnect-form"')
        self.assertNotContains(response, f'href="{reverse("orcid_connect")}"')
        self.assertNotContains(response, 'name="old_password"')

    def test_orcid_only_account_opens_username_and_password_setup(self):
        """
        Offer credential setup instead of a direct destructive submit
        """
        self._use_orcid_only_account()

        response = self.client.get(reverse("account_settings"))

        self.assertContains(response, 'data-bs-target="#orcidSetupModal"')
        self.assertContains(response, 'name="orcid_setup-username"')
        self.assertContains(response, 'name="orcid_setup-password1"')
        self.assertContains(response, 'name="orcid_setup-password2"')
        self.assertNotContains(response, 'form="orcid-disconnect-form"')

    def test_disconnect_preserves_account_data_and_local_login(self):
        """
        Remove only verified identity fields and retain ordinary account access
        """
        response = self.client.post(self.disconnect_url, {"orcid": self.orcid})

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.authenticated_orcid)
        self.assertIsNone(self.profile.orcid_authenticated_at)
        self.assertIsNotNone(self.profile.orcid_disconnected_at)
        self.assertEqual(self.profile.orcid, "legacy-unverified-text")
        self.assertEqual(self.profile.institution, "Research group")
        self.assertTrue(JSONData.objects.filter(pk=self.data.pk, owner=self.user).exists())
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "Quartz!Mosaic72River"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_disconnect_clears_pending_oauth_and_displays_connect_again(self):
        """
        Cancel the browser's outstanding authorization after a successful unlink
        """
        session = self.client.session
        session[ORCID_TRANSACTION_SESSION_KEY] = {"state": "pending-old-state"}
        session.save()

        response = self.client.post(
            self.disconnect_url, {"orcid": self.orcid}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(ORCID_TRANSACTION_SESSION_KEY, self.client.session)
        self.assertContains(response, "Not connected")
        self.assertContains(response, f'href="{reverse("orcid_connect")}"')

    def test_disconnect_refuses_an_account_without_a_password(self):
        """
        Enforce lockout protection even when the browser bypasses the modal
        """
        self._use_orcid_only_account()

        response = self.client.post(self.disconnect_url, {"orcid": self.orcid})

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)
        self.assertIsNone(self.profile.orcid_disconnected_at)

    def test_stale_disconnect_form_cannot_remove_a_different_identity(self):
        """
        Compare the submitted identity with the current verified association
        """
        response = self.client.post(
            self.disconnect_url, {"orcid": "0000-0002-1694-233X"}
        )

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)

    def test_forged_target_does_not_change_another_users_profile(self):
        """
        Always resolve the disconnect target from the authenticated session
        """
        other = User.objects.create_user(username="other-researcher")
        other_profile = AccountProfile.objects.create(
            user=other, authenticated_orcid="0000-0002-1694-233X"
        )

        response = self.client.post(
            self.disconnect_url, {"orcid": self.orcid, "user_id": other.pk}
        )

        self.assertRedirects(response, reverse("account_settings"))
        other_profile.refresh_from_db()
        self.assertEqual(other_profile.authenticated_orcid, "0000-0002-1694-233X")
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.authenticated_orcid)

    def test_repeated_disconnect_is_safe(self):
        """
        Treat an already disconnected identity as a harmless repeat
        """
        for _attempt in range(2):
            response = self.client.post(self.disconnect_url, {"orcid": self.orcid})
            self.assertRedirects(response, reverse("account_settings"))
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_endpoints_require_login_post_and_csrf(self):
        """
        Reject unauthenticated requests and cross site or read only mutations
        """
        for url in (self.disconnect_url, self.setup_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 405)
                protected_client = Client(enforce_csrf_checks=True)
                protected_client.force_login(self.user)
                response = protected_client.post(url, {"orcid": self.orcid})
                self.assertEqual(response.status_code, 403)
                anonymous_client = Client()
                response = anonymous_client.post(url, {"orcid": self.orcid})
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(f"{settings.LOGIN_URL}?next="))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)

    def test_setup_updates_same_account_then_asks_before_disconnecting(self):
        """
        Save credentials without unlinking and require a separate yes action
        """
        self._use_orcid_only_account()

        response = self.client.post(self.setup_url, self._setup_data(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Username and password set successfully.")
        self.assertTrue(response.context["show_orcid_disconnect_confirmation"])
        self.assertContains(response, "Continue disconnecting ORCID?")
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.username, "chosen-researcher")
        self.assertTrue(self.user.check_password("Quartz!Mosaic72River"))
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

        response = self.client.post(self.disconnect_url, {"orcid": self.orcid})
        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.authenticated_orcid)
        self.assertTrue(JSONData.objects.filter(pk=self.data.pk, owner=self.user).exists())
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": "chosen-researcher", "password": "Quartz!Mosaic72River"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_declining_confirmation_keeps_credentials_and_orcid(self):
        """
        Closing the confirmation performs no unlink and does not undo setup
        """
        self._use_orcid_only_account()
        self.client.post(self.setup_url, self._setup_data(), follow=True)

        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_orcid_disconnect_confirmation"])
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertTrue(self.user.has_usable_password())
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)

    def test_stale_profile_save_preserves_new_password_after_disconnect(self):
        """
        Keep new credentials when an older profile submission finishes later
        """
        self._use_orcid_only_account()
        stale_form = AccountSettingsForm(
            data={
                "username": self.user.username,
                "email": self.user.email,
                "institution": "Updated research group",
            },
            instance=User.objects.get(pk=self.user.pk),
        )
        self.assertTrue(stale_form.is_valid(), stale_form.errors)
        self.client.post(self.setup_url, self._setup_data(), follow=True)
        self.client.post(self.disconnect_url, {"orcid": self.orcid})

        stale_form.save()

        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertTrue(self.user.check_password("Quartz!Mosaic72River"))
        self.assertIsNone(self.profile.authenticated_orcid)

    def test_invalid_setup_keeps_profile_form_on_its_own_endpoint(self):
        """
        Keep profile edits working after the setup modal reports an error
        """
        self._use_orcid_only_account()

        response = self.client.post(
            self.setup_url, self._setup_data(**{"orcid_setup-username": "has space"})
        )

        self.assertContains(
            response,
            f'<form method="post" action="{reverse("account_settings")}" novalidate>',
        )

    def test_invalid_setup_keeps_modal_open_and_leaves_credentials_unchanged(self):
        """
        Render field errors without saving partial usernames or passwords
        """
        self._use_orcid_only_account()
        User.objects.create_user(username="already-taken")
        cases = (
            ({"orcid_setup-username": "ALREADY-TAKEN"}, "username"),
            ({"orcid_setup-username": "has space"}, "username"),
            ({"orcid_setup-password1": "123", "orcid_setup-password2": "123"}, "password2"),
            ({"orcid_setup-password2": "Mismatch!Another57"}, "password2"),
        )
        for overrides, field in cases:
            with self.subTest(field=field, overrides=overrides):
                response = self.client.post(self.setup_url, self._setup_data(**overrides))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["show_orcid_setup"])
                form = response.context["orcid_setup_form"]
                self.assertIn(field, form.errors)
                self.assertContains(response, str(form.errors[field][0]))
                self.user.refresh_from_db()
                self.profile.refresh_from_db()
                self.assertFalse(self.user.has_usable_password())
                self.assertEqual(self.user.username, "orcid_0000000214512715")
                self.assertEqual(self.profile.authenticated_orcid, self.orcid)

    def test_setup_cannot_overwrite_existing_local_credentials(self):
        """
        Refuse a stale setup submission after a local password already exists
        """
        response = self.client.post(self.setup_url, self._setup_data())

        self.assertRedirects(response, reverse("account_settings"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "local-researcher")
        self.assertTrue(self.user.check_password("Quartz!Mosaic72River"))

    def test_setup_requires_the_current_verified_identity(self):
        """
        Reject stale or unverified identity claims before accepting credentials
        """
        self._use_orcid_only_account()
        response = self.client.post(
            self.setup_url, self._setup_data(orcid="0000-0002-1694-233X")
        )
        self.assertRedirects(response, reverse("account_settings"))
        self.profile.authenticated_orcid = None
        self.profile.save(update_fields=["authenticated_orcid"])
        response = self.client.post(self.setup_url, self._setup_data())
        self.assertRedirects(response, reverse("account_settings"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
