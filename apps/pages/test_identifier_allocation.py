import copy
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import upload_services
from .models import DataNotification, JSONData
from .upload_test_data import valid_upload_object, variant_field_names


class IdentifierAllocationTests(TestCase):
    """
    Compare generated identifiers with Ronak's template and check safe saves
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create synthetic metadata and isolated owners
        """
        cls.other = User.objects.create_user(username="allocation-other")
        cls.owner = User.objects.create_user(username="allocation-owner")

    def setUp(self):
        """
        Prepare fresh metadata without a supplied identifier
        """
        self.data = valid_upload_object()

    def _prepare(self, data=None, shared_users=()):
        """
        Prepare an object before inserting possible late identifier conflicts

        Parameters
        ----------
        data : dict or None
            Metadata to copy, or the default synthetic object.
        shared_users : tuple
            Recipients for checking notification and rollback behavior.

        Returns
        -------
        PreparedJSONData
            Object ready for the transactional save service.
        """
        data = copy.deepcopy(self.data if data is None else data)
        data["identifier"] = upload_services.generate_data_identifier(data)
        return upload_services.PreparedJSONData(
            data=data, access_type="c", shared_users=shared_users,
            size_bytes=upload_services.canonical_json_size(data),
        )

    def test_identifier_matches_ronaks_cleaned_template(self):
        """
        Produce the exact identifier calculated independently by Ronak's script
        """
        # reference: MiMeDat metadata_template.py, checked on 2026-09-28
        self.assertEqual(upload_services.generate_data_identifier(self.data), "49793b40")
        self.assertNotIn("identifier", self.data)
        self.assertFalse(JSONData.objects.exists())

    def test_serialization_and_cleanup_match_ronaks_reference_results(self):
        """
        Preserve the reference handling of text, numeric text and nested empty data
        """
        cases = [
            (dict(self.data, title="铜 – Δοκιμή"), "f1fae0aa"),
            (dict(self.data, discretization_count="1"), "35d2b256"),
            (dict(self.data, title=["Wrapped generated ID"]), "8ccf8eb1"),
            (dict(self.data, phase=[{
                "phase_name": "Copper",
                "constitutive_model": {"elastic_model_name": "Hooke", "optional": {"nested": None}},
                "notes": [None, [], {}, "", 0, False],
            }]), "49793b40"),
            (dict(self.data, RVE_continuity=False, RVE_size=[0, 1, 1]), "86e64d35"),
            (dict(self.data, RVE_continuity=True, RVE_size=[0, 1, 1]), "14c819d5"),
        ]
        for data, expected in cases:
            with self.subTest(expected=expected):
                original = copy.deepcopy(data)
                self.assertEqual(upload_services.generate_data_identifier(data), expected)
                self.assertEqual(data, original)

    def test_field_lookup_uses_ronaks_exact_mandatory_names(self):
        """
        Keep upload compatibility conversions outside the reference calculation
        """
        cpu_alias = copy.deepcopy(self.data)
        cpu_alias["CPU_specifications"] = cpu_alias.pop("processor_specifications")
        self.assertEqual(upload_services.generate_data_identifier(cpu_alias), "359e929d")
        self.assertEqual(upload_services.generate_data_identifier(variant_field_names(self.data)), "d41d8cd9")

    def test_key_order_and_optional_metadata_do_not_change_identifier(self):
        """
        Match the template's sorted object keys and fixed mandatory field order
        """
        reordered = dict(reversed(list(self.data.items())))
        reordered["units"] = dict(reversed(list(reordered["units"].items())))
        reordered["description"] = "An optional note"
        reordered["identifier"] = "Ignored by generation"
        self.assertEqual(upload_services.generate_data_identifier(reordered), "49793b40")

    def test_existing_records_do_not_change_generated_identifier(self):
        """
        Return the same eight characters regardless of occupied or historical IDs
        """
        original = dict(self.data, title="Different stored simulation", identifier="49793b40")
        blocker = JSONData.objects.create(owner=self.other, data=original, access_type="c")
        legacy = JSONData.objects.create(
            owner=self.other, data=dict(self.data, identifier="7id5xh701u"),
            identifier_fingerprint="684a6b9eaf174e77e12ab42a7243ba6509079ee959a3ac7f41562d839ec8e89f",
        )

        with self.assertNumQueries(0):
            self.assertEqual(upload_services.generate_data_identifier(self.data), "49793b40")

        blocker.refresh_from_db()
        legacy.refresh_from_db()
        self.assertEqual(blocker.data, original)
        self.assertEqual(legacy.data["identifier"], "7id5xh701u")

    def test_late_identifier_conflict_rejects_file_without_notifications(self):
        """
        Recheck generated IDs under the save transaction without extending them
        """
        prepared = self._prepare(shared_users=(self.other,))
        earlier = self._prepare(dict(self.data, title="Earlier batch object"))
        original = dict(self.data, title="Private blocker", identifier="49793b40")
        existing = JSONData.objects.create(owner=self.other, data=original, access_type="c")

        with self.assertRaises(upload_services.UploadIdentifierConflict) as caught:
            upload_services.save_prepared_json_data(self.owner, [earlier, prepared])

        self.assertEqual(caught.exception.identifiers, ("49793b40",))
        self.assertFalse(JSONData.objects.filter(owner=self.owner).exists())
        self.assertFalse(DataNotification.objects.exists())
        existing.refresh_from_db()
        self.assertEqual(existing.data, original)

    def test_real_md5_prefix_collision_rejects_both_prepared_objects(self):
        """
        Reject a real eight digit MD5 collision without assigning a longer ID
        """
        first = self._prepare(dict(self.data, title="Ronak collision fixture 15801"), (self.other,))
        second = self._prepare(dict(self.data, title="Ronak collision fixture 17431"))
        self.assertEqual(first.data["identifier"], "13bc94e3")
        self.assertEqual(second.data["identifier"], "13bc94e3")

        with self.assertRaises(upload_services.UploadIdentifierConflict):
            upload_services.save_prepared_json_data(self.owner, [first, second])

        self.assertFalse(JSONData.objects.exists())
        self.assertFalse(DataNotification.objects.exists())

    def test_final_quota_includes_the_generated_identifier(self):
        """
        Reject the whole file when the final JSON size exceeds the owner's quota
        """
        prepared = self._prepare(shared_users=(self.other,))
        with self.settings(PILOT_MAX_USER_JSON_BYTES=prepared.size_bytes - 1):
            with self.assertRaises(upload_services.UploadQuotaExceeded):
                upload_services.save_prepared_json_data(self.owner, [prepared])

        self.assertFalse(JSONData.objects.exists())
        self.assertFalse(DataNotification.objects.exists())

    def test_saved_json_keeps_raw_values_and_the_eight_character_identifier(self):
        """
        Apply template cleanup only to hashing while preserving stored curves
        """
        prepared = self._prepare(shared_users=(self.other,))
        saved = upload_services.save_prepared_json_data(self.owner, [prepared])[0]
        self.client.force_login(self.owner)
        response = self.client.get(reverse("json_data_export", args=[saved.pk]))

        self.assertEqual(saved.data, dict(self.data, identifier="49793b40"))
        self.assertEqual(saved.identifier_fingerprint, "")
        self.assertEqual(saved.size_bytes, prepared.size_bytes)
        self.assertEqual(json.loads(response.content), saved.data)
        self.assertEqual(saved.data["stress"]["equivalent_stress"], [0, 1])
        self.assertFalse(saved.data["RVE_continuity"])
        self.assertEqual(saved.shared_users.get(), self.other)
        self.assertIn("49793b40", DataNotification.objects.get().message)
