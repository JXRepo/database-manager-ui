from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from .forms import AccountSettingsForm
from .models import AccountProfile


class AccountProfileFieldsTests(TestCase):
    """
    Exercise editing optional research details without changing verified identity
    """

    def setUp(self):
        """
        Sign in an existing account with a verified ORCID connection
        """
        self.user = User.objects.create_user(username="profile-owner", password="password")
        self.profile = AccountProfile.objects.create(
            user=self.user,
            authenticated_orcid="0000-0002-1825-0097",
        )
        self.client.force_login(self.user)
        self.data = {
            "username": "profile-owner",
            "email": "researcher@example.com",
            "display_name": "Ada Researcher",
            "institution": "Materials Institute",
            "department": "Computational Materials",
            "position": "Research Fellow",
            "website": "https://example.com/ada",
            "research_keywords": "Crystal plasticity, microstructure",
        }

    def test_settings_save_research_fields_and_keep_login_name_separate(self):
        """
        Persist every optional detail and expose it when reopening settings
        """
        response = self.client.post(reverse("account_settings"), self.data)

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "profile-owner")
        for field_name in (
            "display_name", "department", "position", "website", "research_keywords",
        ):
            with self.subTest(field=field_name):
                self.assertEqual(getattr(self.profile, field_name, None), self.data[field_name])

        response = self.client.get(reverse("account_settings"))
        for field_name in (
            "display_name", "department", "position", "website", "research_keywords",
        ):
            self.assertIn(field_name, response.context["form"].fields)
            self.assertEqual(response.context["form"][field_name].value(), self.data[field_name])

    def test_optional_fields_can_be_cleared(self):
        """
        Allow a user to remove all optional research details
        """
        self.client.post(reverse("account_settings"), self.data)
        response = self.client.post(
            reverse("account_settings"), {"username": "profile-owner"},
        )

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        for field_name in (
            "display_name", "institution", "department", "position", "website",
            "research_keywords",
        ):
            with self.subTest(field=field_name):
                self.assertEqual(getattr(self.profile, field_name, None), "")

    def test_oversized_fields_reject_the_entire_settings_update(self):
        """
        Reject oversized profile input before persisting any account changes
        """
        values = {
            "display_name": "N" * 256,
            "department": "D" * 256,
            "position": "P" * 256,
            "website": "https://example.com/" + "w" * 482,
            "research_keywords": "K" * 1001,
        }
        for field_name, value in values.items():
            with self.subTest(field=field_name):
                response = self.client.post(
                    reverse("account_settings"), {**self.data, field_name: value},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field_name, response.context["form"].errors)
                self.user.refresh_from_db()
                self.profile.refresh_from_db()
                self.assertEqual(self.user.email, "")
                self.assertEqual(self.profile.institution, "")

    def test_website_rejects_non_web_schemes(self):
        """
        Refuse unsafe or unsupported homepage schemes in settings
        """
        for value in ("javascript:alert(1)", "ftp://example.com/file", "file:///etc/passwd"):
            with self.subTest(website=value):
                response = self.client.post(
                    reverse("account_settings"), {**self.data, "website": value},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("website", response.context["form"].errors)
                self.user.refresh_from_db()
                self.assertEqual(self.user.email, "")

    def test_model_validation_rejects_non_web_schemes(self):
        """
        Apply the same homepage restriction outside the settings form
        """
        self.profile.website = "ftp://example.com/file"
        with self.assertRaises(ValidationError) as error:
            self.profile.full_clean()
        self.assertIn("website", error.exception.message_dict)

    def test_website_accepts_http_and_https(self):
        """
        Keep ordinary public homepage URLs available for manual editing
        """
        for value in ("http://example.com/ada", "https://example.com/ada"):
            with self.subTest(website=value):
                response = self.client.post(
                    reverse("account_settings"), {**self.data, "website": value},
                )
                self.assertRedirects(response, reverse("account_settings"))
                self.profile.refresh_from_db()
                self.assertEqual(getattr(self.profile, "website", None), value)

    def test_forged_orcid_values_do_not_change_verified_identity(self):
        """
        Ignore identity fields submitted alongside editable research details
        """
        response = self.client.post(
            reverse("account_settings"),
            {
                **self.data,
                "orcid": "0000-0001-5109-3700",
                "authenticated_orcid": "0000-0001-5109-3700",
                "user": "999",
            },
        )

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, "0000-0002-1825-0097")
        self.assertEqual(self.profile.orcid, "")
        self.assertEqual(self.profile.user_id, self.user.pk)

    def test_settings_escape_long_profile_content(self):
        """
        Render long supplied names and keywords as text in the form and summary
        """
        name = '<script>alert("name")</script>' + "N" * 220
        keywords = '<img src=x onerror="alert(1)">' + "K" * 950
        response = self.client.post(
            reverse("account_settings"),
            {**self.data, "display_name": name, "research_keywords": keywords},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, escape(name))
        self.assertContains(response, escape(keywords))
        self.assertNotContains(response, '<script>alert("name")</script>')
        self.assertNotContains(response, '<img src=x onerror="alert(1)">')

    def test_settings_form_is_available_without_an_existing_profile(self):
        """
        Leave new optional fields blank when an account has no profile yet
        """
        user = User.objects.create_user(username="no-profile")
        form = AccountSettingsForm(instance=user)

        for field_name in (
            "display_name", "department", "position", "website", "research_keywords",
        ):
            with self.subTest(field=field_name):
                self.assertIn(field_name, form.fields)
                self.assertFalse(form.fields[field_name].required)
                self.assertFalse(form[field_name].value())
