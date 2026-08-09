from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.db.migrations.exceptions import NodeNotFoundError
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import JSONData


class JSONDataSizeBytesModelTests(TestCase):
    """
    Test JSONData byte accounting defaults
    """

    def setUp(self):
        """
        Create a user for direct JSONData fixtures
        """
        self.owner = get_user_model().objects.create_user(
            username="fixture-owner",
            email="fixture-owner@example.com",
            password="password",
        )

    def test_size_bytes_defaults_to_zero_for_direct_fixtures(self):
        """
        Direct JSONData fixtures keep size_bytes at zero by default
        """
        json_data = JSONData.objects.create(
            owner=self.owner,
            data={"phase": "alpha"},
            access_type="c",
        )

        self.assertEqual(getattr(json_data, "size_bytes", None), 0)


class RateLimitBucketModelTests(TestCase):
    """
    Test database-backed rate limit bucket constraints
    """

    def test_bucket_identity_must_be_unique(self):
        """
        Buckets cannot share the same identity tuple
        """
        try:
            rate_limit_bucket_model = apps.get_model("pages", "RateLimitBucket")
        except LookupError as exc:
            self.fail(str(exc))

        rate_limit_bucket_model.objects.create(
            scope="upload",
            identifier_hash="a" * 64,
            window_seconds=60,
            window_id=123456,
            count=1,
            expires_at=timezone.now(),
        )

        with self.assertRaises(IntegrityError):
            rate_limit_bucket_model.objects.create(
                scope="upload",
                identifier_hash="a" * 64,
                window_seconds=60,
                window_id=123456,
                count=2,
                expires_at=timezone.now(),
            )


class JSONDataSizeBytesMigrationTests(TransactionTestCase):
    """
    Test the historical backfill for JSONData.size_bytes
    """

    migrate_from = ("pages", "0006_accountprofile")
    migrate_to = ("pages", "0007_jsondata_size_bytes_and_rate_limit_bucket")
    reset_sequences = True

    def setUp(self):
        """
        Migrate to the old state, seed data, then migrate forward
        """
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.runtime_targets = self.executor.loader.graph.leaf_nodes("pages")
        self._migrate([self.migrate_from])

        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        user_model = old_apps.get_model("auth", "User")
        json_data_model = old_apps.get_model("pages", "JSONData")

        owner = user_model.objects.create(
            username="migration-owner",
            email="migration-owner@example.com",
        )
        self.object_id = json_data_model.objects.create(
            owner=owner,
            data={"phase": "α"},
            access_type="c",
        ).pk

        self.executor = MigrationExecutor(connection)
        self._migrate([self.migrate_to])
        self.apps = self.executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        """
        Return the schema to the runtime state for isolation
        """
        self.executor = MigrationExecutor(connection)
        self._migrate(self.runtime_targets)
        super().tearDown()

    def _migrate(self, targets):
        """
        Migrate to target states or fail with a clear message
        """
        try:
            self.executor.migrate(targets)
        except NodeNotFoundError as exc:
            self.fail(f"Missing migration target: {exc}")

    def test_backfill_sets_size_bytes_to_compact_utf8_json_length(self):
        """
        The backfill stores compact UTF-8 byte length for existing rows
        """
        json_data_model = self.apps.get_model("pages", "JSONData")
        migrated_object = json_data_model.objects.get(pk=self.object_id)
        # Hand-checked literal: {"phase":"α"} is 12 characters plus 2 UTF-8 bytes for α.
        self.assertEqual(migrated_object.size_bytes, 14)

    def test_restore_targets_follow_the_current_migration_graph(self):
        """
        Historical tests restore every current pages migration leaf
        """
        current_executor = MigrationExecutor(connection)
        current_targets = current_executor.loader.graph.leaf_nodes("pages")

        self.assertEqual(self.runtime_targets, current_targets)
