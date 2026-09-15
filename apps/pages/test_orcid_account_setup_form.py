from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .forms import ORCIDAccountSetupForm


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ORCIDAccountSetupFormTests(TestCase):
    """
    Validate local credentials for the existing ORCID account
    """

    def setUp(self):
        """
        Create an ORCID account without a usable password
        """
        self.user = User.objects.create_user(
            username="orcid_researcher",
            email="researcher@example.org",
        )
        self.data = {
            "username": "new_researcher",
            "password1": "Quartz!Mosaic72River",
            "password2": "Quartz!Mosaic72River",
        }

    def test_username_and_password_update_the_existing_account(self):
        """
        Save new credentials without replacing the account or its metadata
        """
        self.user.is_staff = True
        self.user.first_name = "Researcher"
        self.user.save(update_fields=["is_staff", "first_name"])
        account_id = self.user.pk
        form = ORCIDAccountSetupForm(data=self.data, instance=self.user)

        self.assertTrue(form.is_valid(), form.errors)
        saved_user = form.save()

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(saved_user.pk, account_id)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "new_researcher")
        self.assertTrue(self.user.check_password("Quartz!Mosaic72River"))
        self.assertEqual(self.user.email, "researcher@example.org")
        self.assertEqual(self.user.first_name, "Researcher")
        self.assertTrue(self.user.is_staff)

    def test_current_username_is_accepted_for_the_same_user(self):
        """
        Exclude the current account from username uniqueness checks
        """
        form = ORCIDAccountSetupForm(
            data={**self.data, "username": self.user.username},
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_current_username_can_change_letter_case(self):
        """
        Allow a case change when the matching username belongs to this user
        """
        form = ORCIDAccountSetupForm(
            data={**self.data, "username": "ORCID_RESEARCHER"},
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_taken_username_is_rejected_ignoring_case(self):
        """
        Reject names already held by another user regardless of letter case
        """
        User.objects.create_user(username="TakenName")

        for username in ("TakenName", "takenname", "TAKENNAME"):
            with self.subTest(username=username):
                form = ORCIDAccountSetupForm(
                    data={**self.data, "username": username},
                    instance=self.user,
                )
                self.assertFalse(form.is_valid())
                self.assertIn("username", form.errors)

    def test_usernames_with_whitespace_are_rejected(self):
        """
        Reject internal and surrounding whitespace instead of silently trimming it
        """
        for username in ("two names", " leading", "trailing ", "tab\tname", "a\u00a0b"):
            with self.subTest(username=username):
                form = ORCIDAccountSetupForm(
                    data={**self.data, "username": username},
                    instance=self.user,
                )
                self.assertFalse(form.is_valid())
                self.assertIn("username", form.errors)

    def test_username_longer_than_150_characters_is_rejected(self):
        """
        Enforce the existing user model's username length limit
        """
        form = ORCIDAccountSetupForm(
            data={**self.data, "username": "a" * 151},
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_valid_unicode_username_is_accepted(self):
        """
        Keep Django's support for Unicode researcher usernames
        """
        form = ORCIDAccountSetupForm(
            data={**self.data, "username": "研究者_Änne"},
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_weak_passwords_are_rejected(self):
        """
        Preserve minimum length and common password validation
        """
        for password in ("123", "password", "1234567890"):
            with self.subTest(password=password):
                form = ORCIDAccountSetupForm(
                    data={**self.data, "password1": password, "password2": password},
                    instance=self.user,
                )
                self.assertFalse(form.is_valid())
                self.assertIn("password2", form.errors)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_password_confirmation_must_match(self):
        """
        Reject different password and confirmation values
        """
        form = ORCIDAccountSetupForm(
            data={**self.data, "password2": "Another!Valid73Password"},
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_password_similarity_uses_the_new_username(self):
        """
        Validate the password against the chosen name instead of the old ORCID name
        """
        form = ORCIDAccountSetupForm(
            data={
                "username": "MosaicResearcher72",
                "password1": "MosaicResearcher72!",
                "password2": "MosaicResearcher72!",
            },
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        errors = form.errors.as_data()["password2"]
        self.assertIn("password_too_similar", [error.code for error in errors])

    def test_submitted_account_and_privilege_fields_are_ignored(self):
        """
        Limit updates to the bound account's username and password
        """
        other_user = User.objects.create_user(username="other_researcher")
        form = ORCIDAccountSetupForm(
            data={
                **self.data,
                "pk": other_user.pk,
                "user": other_user.pk,
                "user_id": other_user.pk,
                "email": "changed@example.org",
                "is_staff": "true",
                "is_superuser": "true",
                "is_active": "false",
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_user = form.save()

        self.assertEqual(saved_user.pk, self.user.pk)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "researcher@example.org")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        other_user.refresh_from_db()
        self.assertEqual(other_user.username, "other_researcher")
        self.assertFalse(other_user.has_usable_password())
