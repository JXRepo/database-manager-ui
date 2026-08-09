from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import NodeNotFoundError
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .forms import AccountSettingsForm
from .models import AccountProfile


class VerifiedORCIDModelTests(TestCase):
    """
    Test verified ORCID identity constraints
    """

    def test_multiple_profiles_allow_null_verified_identity(self):
        """
        Multiple profiles can remain without a verified ORCID identity
        """
        user_model = get_user_model()
        first_user = user_model.objects.create_user(username="first-user")
        second_user = user_model.objects.create_user(username="second-user")

        first_profile = AccountProfile.objects.create(user=first_user)
        second_profile = AccountProfile.objects.create(user=second_user)

        self.assertIsNone(first_profile.authenticated_orcid)
        self.assertIsNone(second_profile.authenticated_orcid)

    def test_duplicate_verified_identity_is_rejected(self):
        """
        Two profiles cannot claim the same verified ORCID identity
        """
        user_model = get_user_model()
        first_user = user_model.objects.create_user(username="first-user")
        second_user = user_model.objects.create_user(username="second-user")
        AccountProfile.objects.create(
            user=first_user,
            authenticated_orcid="0000-0002-1451-2715",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountProfile.objects.create(
                user=second_user,
                authenticated_orcid="0000-0002-1451-2715",
            )


class AccountSettingsORCIDBoundaryTests(TestCase):
    """
    Test that account settings cannot create ORCID identity claims
    """

    def setUp(self):
        """
        Create a local account with an unverified legacy ORCID value
        """
        self.user = get_user_model().objects.create_user(
            username="settings-user",
            email="settings@example.com",
            password="password",
        )
        self.profile = AccountProfile.objects.create(
            user=self.user,
            orcid="legacy-orcid-value",
        )

    def test_orcid_fields_are_not_editable_in_account_settings_form(self):
        """
        Account settings expose no editable ORCID fields
        """
        form = AccountSettingsForm(instance=self.user)

        self.assertNotIn("orcid", form.fields)
        self.assertNotIn("authenticated_orcid", form.fields)
        self.assertNotIn("orcid_authenticated_at", form.fields)

    def test_settings_post_cannot_change_any_orcid_identity_field(self):
        """
        Forged account settings keys leave every ORCID field unchanged
        """
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("account_settings"),
            {
                "username": self.user.username,
                "email": self.user.email,
                "institution": "ICAMS",
                "orcid": "0000-0002-1451-2715",
                "authenticated_orcid": "0000-0002-1451-2715",
                "orcid_authenticated_at": "2026-08-09T12:00:00Z",
            },
        )

        self.assertRedirects(response, reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.institution, "ICAMS")
        self.assertEqual(self.profile.orcid, "legacy-orcid-value")
        self.assertIsNone(self.profile.authenticated_orcid)
        self.assertIsNone(self.profile.orcid_authenticated_at)

    def test_settings_hide_legacy_orcid_and_show_disconnected_status(self):
        """
        Account settings label only the verified ORCID identity
        """
        self.client.force_login(self.user)

        response = self.client.get(reverse("account_settings"))

        self.assertContains(response, "Verified ORCID iD")
        self.assertContains(response, "Not connected")
        self.assertNotContains(response, "legacy-orcid-value")
        self.assertContains(response, reverse("orcid_connect"))

    def test_settings_show_the_verified_orcid_identity(self):
        """
        Account settings display the verified ORCID identity when present
        """
        self.profile.authenticated_orcid = "0000-0002-1451-2715"
        self.profile.save(update_fields=["authenticated_orcid"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("account_settings"))

        self.assertContains(response, "Verified ORCID iD")
        self.assertContains(response, "0000-0002-1451-2715")
        self.assertNotContains(response, "legacy-orcid-value")


class VerifiedORCIDMigrationTests(TransactionTestCase):
    """
    Test migration of the verified ORCID identity boundary
    """

    migrate_from = ("pages", "0007_jsondata_size_bytes_and_rate_limit_bucket")
    migrate_to = ("pages", "0008_accountprofile_authenticated_orcid")
    reset_sequences = True

    def setUp(self):
        """
        Seed legacy profile data before migrating to the verified fields
        """
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.runtime_targets = self.executor.loader.graph.leaf_nodes("pages")
        self._migrate([self.migrate_from])

        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        user_model = old_apps.get_model("auth", "User")
        profile_model = old_apps.get_model("pages", "AccountProfile")
        user = user_model.objects.create(username="legacy-user")
        self.profile_id = profile_model.objects.create(
            user=user,
            orcid="0000-0002-1451-2715",
        ).pk

        self.executor = MigrationExecutor(connection)
        self._migrate([self.migrate_to])
        self.apps = self.executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        """
        Restore every current pages migration leaf after the test
        """
        self.executor = MigrationExecutor(connection)
        self._migrate(self.runtime_targets)
        super().tearDown()

    def _migrate(self, targets):
        """
        Migrate to target states or fail with a clear message

        Parameters
        ----------
        targets : list[tuple[str, str]]
            Migration targets to apply.
        """
        try:
            self.executor.migrate(targets)
        except NodeNotFoundError as exc:
            self.fail(f"Missing migration target: {exc}")

    def test_migration_preserves_legacy_orcid_without_verifying_it(self):
        """
        Existing legacy ORCID text remains unverified after migration
        """
        profile_model = self.apps.get_model("pages", "AccountProfile")
        migrated_profile = profile_model.objects.get(pk=self.profile_id)

        self.assertEqual(migrated_profile.orcid, "0000-0002-1451-2715")
        self.assertIsNone(migrated_profile.authenticated_orcid)
        self.assertIsNone(migrated_profile.orcid_authenticated_at)
