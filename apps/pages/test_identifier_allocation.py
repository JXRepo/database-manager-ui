import copy
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.query import QuerySet
from django.test import TestCase
from django.urls import reverse

from . import upload_services
from .models import DataNotification, JSONData


EXAMPLE_FINGERPRINT = "e52f02f5c6fa72b995669aa804a6b903fc6989bff2f42d25ffb632fc9a43dad0"
EXAMPLE_IDENTIFIER_STREAM = "4fvjlgcqe376d07x25ykq2uu7nfq35tpuuzja7it4mzw8bymp5"


class IdentifierAllocationTests(TestCase):
    """
    Exercise identifier allocation before and during transactional saves
    """

    @classmethod
    def setUpTestData(cls):
        """
        Load example metadata and create isolated owners
        """
        cls.other = User.objects.create_user(username="allocation-other")
        cls.owner = User.objects.create_user(username="allocation-owner")
        path = Path(settings.BASE_DIR) / "example_json_files/a46fde6c1_public.json"
        cls.example = json.loads(path.read_text(encoding="utf-8"))

    def setUp(self):
        """
        Prepare fresh metadata without a supplied identifier
        """
        self.data = copy.deepcopy(self.example)
        self.data.pop("identifier")

    def _prepare(self, data=None, shared_users=()):
        """
        Prepare automatic allocation using the public service contract

        The candidate is deliberately chosen before tests insert late conflicts.

        Parameters
        ----------
        data : dict or None
            Metadata to copy, or the example metadata when omitted.
        shared_users : tuple
            Recipients for checking notification and rollback behavior.

        Returns
        -------
        PreparedJSONData
            Object ready for the transactional save service.
        """
        data = copy.deepcopy(self.data if data is None else data)
        fingerprint = upload_services.data_fingerprint(data)
        data["identifier"] = upload_services.generate_data_identifier(data)
        return upload_services.PreparedJSONData(
            data=data,
            access_type="c",
            shared_users=shared_users,
            size_bytes=len(json.dumps(
                data, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")),
            identifier_fingerprint=fingerprint,
        )

    def _occupy_identifier(self, identifier):
        """
        Store different required content under a candidate identifier

        The other owner's private row must participate in global allocation.

        Parameters
        ----------
        identifier : str
            Candidate identifier to occupy before the next allocation.

        Returns
        -------
        JSONData
            Existing record that allocation must preserve.
        """
        return JSONData.objects.create(
            owner=self.other,
            data=dict(self.data, title="Different stored simulation", identifier=identifier),
            access_type="c",
            size_bytes=1,
        )

    def test_generation_returns_short_identifier_without_writing_records(self):
        """
        Keep preparation free of writes while returning a usable short ID
        """
        identifier = upload_services.generate_data_identifier(self.data)

        self.assertRegex(identifier, r"^[0-9a-z]{8}$")
        self.assertEqual(identifier, "4fvjlgcq")
        self.assertFalse(JSONData.objects.exists())
        self.assertNotIn("identifier", self.data)

    def test_distinct_content_collisions_extend_one_character_at_a_time(self):
        """
        Preserve occupied identifiers and use the next available prefix
        """
        first = self._occupy_identifier("4fvjlgcq")

        self.assertEqual(
            upload_services.generate_data_identifier(self.data), "4fvjlgcqe",
        )
        second = self._occupy_identifier("4fvjlgcqe")
        self.assertEqual(
            upload_services.generate_data_identifier(self.data), "4fvjlgcqe3",
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.data["identifier"], "4fvjlgcq")
        self.assertEqual(second.data["identifier"], "4fvjlgcqe")
        self.assertEqual(JSONData.objects.count(), 2)

    def test_late_collision_updates_saved_bytes_and_notification_identifier(self):
        """
        Reallocate after preparation before accounting or notifying recipients
        """
        prepared = self._prepare(shared_users=(self.other,))
        blocker = self._occupy_identifier("4fvjlgcq")

        saved = upload_services.save_prepared_json_data(self.owner, [prepared])[0]

        self.assertEqual(saved.data["identifier"], "4fvjlgcqe")
        self.assertEqual(saved.size_bytes, prepared.size_bytes + 1)
        self.assertEqual(saved.identifier_fingerprint, EXAMPLE_FINGERPRINT)
        self.assertEqual(saved.shared_users.get(), self.other)
        notification = DataNotification.objects.get()
        self.assertEqual(notification.data_object, saved)
        self.assertIn("4fvjlgcqe", notification.message)
        blocker.refresh_from_db()
        self.assertEqual(blocker.data["identifier"], "4fvjlgcq")

    def test_final_allocation_follows_global_then_owner_lock_requests(self):
        """
        Preserve lock ordering before repeating allocation inside the transaction

        SQLite exercises real queries but cannot verify PostgreSQL row blocking.
        """
        prepared = self._prepare()
        events = []
        real_fetch_all = QuerySet._fetch_all
        real_resolve = upload_services._resolve_generated_identifier

        def observe_fetch(queryset):
            """
            Record actual users fetched by queries requesting row locks

            Parameters
            ----------
            queryset : QuerySet
                Real query whose normal database evaluation is preserved.
            """
            already_evaluated = queryset._result_cache is not None
            real_fetch_all(queryset)
            if (
                not already_evaluated
                and queryset.model is User
                and queryset.query.select_for_update
            ):
                for user in queryset._result_cache:
                    events.append(("lock", user.pk))

        def observe_allocation(fingerprint, pending_objects):
            """
            Record final resolution while retaining normal collision checks

            Parameters
            ----------
            fingerprint : str
                Full content digest to resolve.
            pending_objects : sequence
                Other objects reserved for the batch.

            Returns
            -------
            str
                Identifier returned by the real allocation function.
            """
            events.append(("allocate", fingerprint))
            return real_resolve(fingerprint, pending_objects)

        with (
            patch.object(QuerySet, "_fetch_all", observe_fetch),
            patch.object(upload_services, "_resolve_generated_identifier", observe_allocation),
        ):
            saved = upload_services.save_prepared_json_data(self.owner, [prepared])

        self.assertEqual(events, [
            ("lock", self.other.pk),
            ("lock", self.owner.pk),
            ("allocate", EXAMPLE_FINGERPRINT),
        ])
        self.assertEqual(saved[0].data["identifier"], "4fvjlgcq")

    def test_late_extension_over_quota_creates_no_rows_or_notifications(self):
        """
        Reject the extra identifier byte rather than exceeding the live quota
        """
        prepared = self._prepare(shared_users=(self.other,))
        self._occupy_identifier("4fvjlgcq")

        with self.settings(PILOT_MAX_USER_JSON_BYTES=prepared.size_bytes):
            with self.assertRaises(upload_services.UploadQuotaExceeded):
                upload_services.save_prepared_json_data(self.owner, [prepared])

        self.assertFalse(JSONData.objects.filter(owner=self.owner).exists())
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertFalse(DataNotification.objects.exists())

    def test_late_same_fingerprint_conflict_rejects_the_entire_batch(self):
        """
        Keep identical content a duplicate even if its stored ID was extended
        """
        prepared = self._prepare(shared_users=(self.other,))
        earlier = self._prepare(dict(self.data, title="Earlier batch object"))
        existing = JSONData.objects.create(
            owner=self.other,
            data=dict(self.data, identifier="4fvjlgcqe"),
            identifier_fingerprint=EXAMPLE_FINGERPRINT,
            access_type="c",
            size_bytes=1,
        )

        with self.assertRaises(upload_services.UploadIdentifierConflict) as caught:
            upload_services.save_prepared_json_data(self.owner, [earlier, prepared])

        self.assertEqual(caught.exception.identifiers, ("4fvjlgcq",))
        self.assertFalse(JSONData.objects.filter(owner=self.owner).exists())
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertFalse(DataNotification.objects.exists())
        existing.refresh_from_db()
        self.assertEqual(existing.data["identifier"], "4fvjlgcqe")

    def test_final_extension_reserves_later_supplied_identifiers(self):
        """
        Avoid every supplied batch identifier during final automatic allocation
        """
        automatic = self._prepare()
        self._occupy_identifier("4fvjlgcq")
        supplied = upload_services.PreparedJSONData(
            data={"identifier": "4fvjlgcqe"},
            access_type="c",
            shared_users=(),
            size_bytes=17,
        )

        saved = upload_services.save_prepared_json_data(self.owner, [automatic, supplied])

        self.assertEqual(saved[0].data["identifier"], "4fvjlgcqe3")
        self.assertEqual(saved[0].size_bytes, automatic.size_bytes + 2)
        self.assertEqual(saved[1].data, {"identifier": "4fvjlgcqe"})
        self.assertEqual(saved[1].size_bytes, 17)
        self.assertEqual(saved[1].identifier_fingerprint, "")

    def test_fingerprint_stays_internal_when_generated_data_is_exported(self):
        """
        Store the full fingerprint separately without exposing it in JSON
        """
        prepared = self._prepare()
        saved = upload_services.save_prepared_json_data(self.owner, [prepared])[0]
        self.client.force_login(self.owner)

        response = self.client.get(reverse("json_data_export", args=[saved.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved.identifier_fingerprint, EXAMPLE_FINGERPRINT)
        self.assertEqual(saved.data, dict(self.data, identifier="4fvjlgcq"))
        self.assertEqual(json.loads(response.content), saved.data)
        self.assertNotIn("identifier_fingerprint", saved.data)

    def test_existing_fingerprint_keeps_its_extended_identifier(self):
        """
        Reuse the stored duplicate ID even when a shorter prefix is now free
        """
        JSONData.objects.create(
            owner=self.other,
            data=dict(self.data, identifier="4fvjlgcqe3"),
            identifier_fingerprint=EXAMPLE_FINGERPRINT,
            size_bytes=1,
        )
        optional_change = dict(self.data, description="Changed optional description")

        identifier = upload_services.generate_data_identifier(optional_change)

        self.assertEqual(identifier, "4fvjlgcqe3")
        self.assertEqual(JSONData.objects.count(), 1)

    def test_old_full_digest_is_recognized_without_rewriting_the_record(self):
        """
        Retain earlier generated identifiers as duplicate aliases
        """
        old = JSONData.objects.create(
            owner=self.other,
            data=dict(self.data, identifier=EXAMPLE_FINGERPRINT),
            size_bytes=17,
        )

        identifier = upload_services.generate_data_identifier(self.data)

        self.assertEqual(identifier, EXAMPLE_FINGERPRINT)
        old.refresh_from_db()
        self.assertEqual(old.data["identifier"], EXAMPLE_FINGERPRINT)
        self.assertEqual(old.identifier_fingerprint, "")
        self.assertEqual(old.size_bytes, 17)

    def test_exhausted_fingerprint_prefixes_fail_without_writing(self):
        """
        Stop allocation when every finite candidate belongs to other content
        """
        for length in range(8, 51):
            self._occupy_identifier(EXAMPLE_IDENTIFIER_STREAM[:length])

        with self.assertRaises(upload_services.UploadResourceLimitError):
            upload_services.generate_data_identifier(self.data)

        self.assertEqual(JSONData.objects.count(), 43)
        self.assertFalse(JSONData.objects.filter(owner=self.owner).exists())
