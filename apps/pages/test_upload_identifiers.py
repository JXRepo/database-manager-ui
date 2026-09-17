import copy
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import JSONData
from .upload_services import canonical_json_size, generate_data_identifier


class UploadIdentifierTests(TestCase):
    """
    Exercise identifier generation and conflicts through real uploads
    """

    example_fingerprint = "e52f02f5c6fa72b995669aa804a6b903fc6989bff2f42d25ffb632fc9a43dad0"

    @classmethod
    def setUpTestData(cls):
        """
        Load a real example and create two isolated upload owners
        """
        cls.owner = User.objects.create_user(username="identifier-owner", password="password")
        cls.other = User.objects.create_user(username="identifier-other", password="password")
        path = Path(settings.BASE_DIR) / "example_json_files/a46fde6c1_public.json"
        cls.example = json.loads(path.read_text(encoding="utf-8"))

    def setUp(self):
        """
        Sign in and prepare an example without an identifier
        """
        self.client.force_login(self.owner)
        self.data = copy.deepcopy(self.example)
        self.data.pop("identifier")

    def _upload(self, *payloads):
        """
        Submit one or more JSON files through the normal upload endpoint

        Parameters
        ----------
        payloads : object
            JSON payloads assigned numbered filenames.

        Returns
        -------
        HttpResponse
            Response containing the upload outcome.
        """
        files = []
        for index, payload in enumerate(payloads, start=1):
            files.append(SimpleUploadedFile(
                f"file-{index}.json", json.dumps(payload).encode("utf-8"),
                content_type="application/json",
            ))
        return self.client.post(reverse("upload_json"), {"file": files})

    def _messages(self, response):
        """
        Collect visible upload guidance from a response

        Parameters
        ----------
        response : HttpResponse
            Response from the upload endpoint.

        Returns
        -------
        str
            Combined messages for checking error location and guidance.
        """
        return " ".join(str(message) for message in get_messages(response.wsgi_request))

    def test_missing_identifier_is_stored_and_exported_without_other_changes(self):
        """
        Generate an identifier in the object and include its bytes in quota
        """
        response = self._upload(self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 1)
        stored = JSONData.objects.get()
        identifier = stored.data["identifier"]
        self.assertRegex(identifier, r"^[0-9a-z]{8}$")
        self.assertEqual(stored.data, dict(self.data, identifier=identifier))
        self.assertNotIn("identifier", self.data)
        self.assertEqual(stored.identifier_fingerprint, self.example_fingerprint)
        self.assertEqual(stored.size_bytes, canonical_json_size(stored.data))
        exported = self.client.get(reverse("json_data_export", args=[stored.pk]))
        self.assertEqual(json.loads(exported.content), stored.data)
        self.assertNotIn("identifier_fingerprint", json.loads(exported.content))

    def test_generated_identifiers_use_every_lowercase_base36_digit(self):
        """
        Encode the digest using all digits and lowercase letters
        """
        for digit in "0123456789abcdefghijklmnopqrstuvwxyz":
            with self.subTest(digit=digit):
                digest = format(int(digit * 8, 36), "064x")
                with patch("apps.pages.upload_services.hashlib.sha256") as sha256:
                    sha256.return_value.hexdigest.return_value = digest
                    identifier = generate_data_identifier(self.data)
                self.assertEqual(identifier, digit * 8)
        self.assertEqual(JSONData.objects.count(), 0)

    def test_generated_identifier_starts_with_least_significant_digits(self):
        """
        Keep deterministic digest digits in the agreed identifier order
        """
        digest = format(int("76543210", 36), "064x")
        with patch("apps.pages.upload_services.hashlib.sha256") as sha256:
            sha256.return_value.hexdigest.return_value = digest
            identifier = generate_data_identifier(self.data)
        self.assertEqual(identifier, "01234567")

    def test_database_collisions_extend_one_character_at_a_time(self):
        """
        Keep extending when different objects occupy successive prefixes
        """
        first_identifier = generate_data_identifier(self.data)
        first = JSONData.objects.create(
            owner=self.owner,
            data=dict(self.data, identifier=first_identifier, title="First occupier"),
        )
        second_identifier = generate_data_identifier(self.data)
        self.assertEqual(len(first_identifier), 8)
        self.assertEqual(len(second_identifier), 9)
        self.assertTrue(second_identifier.startswith(first_identifier))
        second = JSONData.objects.create(
            owner=self.owner,
            data=dict(self.data, identifier=second_identifier, title="Second occupier"),
        )

        response = self._upload(self.data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 3)
        stored = JSONData.objects.exclude(pk__in=[first.pk, second.pk]).get()
        self.assertEqual(len(stored.data["identifier"]), 10)
        self.assertTrue(stored.data["identifier"].startswith(second_identifier))
        self.assertEqual(stored.owner, self.owner)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.data["identifier"], first_identifier)
        self.assertEqual(second.data["identifier"], second_identifier)

    def test_numeric_looking_identifiers_stay_text_and_block_repeat_uploads(self):
        """
        Preserve numeric and exponent shaped identifiers during digest lookup
        """
        for identifier in ("87654321", "1e234567"):
            with self.subTest(identifier=identifier):
                JSONData.objects.all().delete()
                digest = format(int(identifier[::-1], 36), "064x")
                with patch("apps.pages.views.data_fingerprint", return_value=digest), patch(
                    "apps.pages.upload_services.data_fingerprint", return_value=digest,
                ):
                    self._upload(self.data)
                    self.assertEqual(JSONData.objects.get().data["identifier"], identifier)
                    self.assertIsInstance(generate_data_identifier(self.data), str)
                    response = self._upload(self.data)
                self.assertEqual(JSONData.objects.count(), 1)
                self.assertEqual(JSONData.objects.get().data["identifier"], identifier)
                self.assertIn("already exists", self._messages(response))
                JSONData.objects.all().delete()

    def test_supplied_identifier_collision_in_batch_extends_generated_identifier(self):
        """
        Allocate around an earlier supplied identifier without rejecting data
        """
        prefix = generate_data_identifier(self.data)
        explicit = dict(self.data, identifier=prefix, title="Distinct supplied object")

        response = self._upload([explicit, self.data])

        self.assertEqual(JSONData.objects.count(), 2)
        supplied = JSONData.objects.get(data__identifier=prefix)
        generated = JSONData.objects.exclude(pk=supplied.pk).get()
        self.assertEqual(supplied.data, explicit)
        self.assertEqual(len(generated.data["identifier"]), 9)
        self.assertTrue(generated.data["identifier"].startswith(prefix))
        self.assertNotIn("duplicated", self._messages(response))

    def test_supplied_identifier_collision_across_files_extends_generated_identifier(self):
        """
        Reserve earlier supplied identifiers across files in one submission
        """
        prefix = generate_data_identifier(self.data)
        explicit = dict(self.data, identifier=prefix, title="Distinct file object")

        self._upload(explicit, self.data)

        self.assertEqual(JSONData.objects.count(), 2)
        generated = JSONData.objects.exclude(data__identifier=prefix).get()
        self.assertEqual(len(generated.data["identifier"]), 9)
        self.assertTrue(generated.data["identifier"].startswith(prefix))

    def test_extended_identifier_still_blocks_duplicates_after_occupier_is_deleted(self):
        """
        Find prior generated content even after its original prefix is free
        """
        prefix = generate_data_identifier(self.data)
        occupier = JSONData.objects.create(
            owner=self.owner,
            data=dict(self.data, identifier=prefix, title="Temporary occupier"),
        )
        self._upload(self.data)
        stored = JSONData.objects.exclude(pk=occupier.pk).get()
        identifier = stored.data["identifier"]
        self.assertEqual(len(identifier), 9)
        occupier.delete()

        response = self._upload(dict(self.data, description="Different optional note"))

        self.assertEqual(JSONData.objects.count(), 1)
        stored.refresh_from_db()
        self.assertEqual(stored.data["identifier"], identifier)
        self.assertIn("already exists", self._messages(response))

    def test_supplied_collision_with_same_required_content_is_not_extended(self):
        """
        Reject identical content when its short identifier is already stored
        """
        identifier = generate_data_identifier(self.data)
        supplied = dict(self.data, identifier=identifier)
        self._upload(supplied)

        response = self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, supplied)
        self.assertIn("already exists", self._messages(response))

    def test_reimported_extended_identifier_still_recognizes_its_content(self):
        """
        Recognize an exported long prefix even when its shorter prefix is free
        """
        prefix = generate_data_identifier(self.data)
        occupier = JSONData.objects.create(
            owner=self.owner, data={"identifier": prefix},
        )
        self._upload(self.data)
        stored = JSONData.objects.exclude(pk=occupier.pk).get()
        exported = self.client.get(reverse("json_data_export", args=[stored.pk]))
        payload = json.loads(exported.content)
        self.assertEqual(len(payload["identifier"]), 9)
        JSONData.objects.all().delete()
        self._upload(payload)
        self.assertEqual(JSONData.objects.get().identifier_fingerprint, "")

        response = self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, payload)
        self.assertIn("already exists", self._messages(response))

    def test_legacy_full_digest_blocks_duplicates_without_rewriting_record(self):
        """
        Recognize old generated identifiers without backfilling existing data
        """
        legacy = dict(self.data, identifier=self.example_fingerprint)
        stored = JSONData.objects.create(owner=self.owner, data=legacy)

        response = self._upload(dict(self.data, keywords=["New optional metadata"]))

        self.assertEqual(JSONData.objects.count(), 1)
        stored.refresh_from_db()
        self.assertEqual(stored.data, legacy)
        self.assertEqual(stored.identifier_fingerprint, "")
        self.assertIn("already exists", self._messages(response))

    def test_legacy_full_digest_and_generated_content_conflict_in_either_batch_order(self):
        """
        Apply legacy content deduplication in both directions within a batch
        """
        legacy = dict(self.data, identifier=self.example_fingerprint)
        for legacy_first in (True, False):
            with self.subTest(legacy_first=legacy_first):
                objects = [legacy, self.data] if legacy_first else [self.data, legacy]
                response = self._upload(objects)
                self.assertEqual(JSONData.objects.count(), 1)
                stored = JSONData.objects.get()
                if legacy_first:
                    self.assertEqual(stored.data, legacy)
                else:
                    self.assertRegex(stored.data["identifier"], r"^[0-9a-z]{8}$")
                message = self._messages(response)
                self.assertIn("partially successful", message)
                self.assertIn("file-1.json data object 2", message)
                self.assertIn("duplicated in this upload", message)
                JSONData.objects.all().delete()

    def test_distinct_supplied_identifiers_allow_identical_required_content(self):
        """
        Keep explicit names outside automatic content deduplication
        """
        first = dict(self.data, identifier="Experiment-A_01")
        second = dict(self.data, identifier="Experiment-B_02")
        for generated_first in (True, False):
            with self.subTest(generated_first=generated_first):
                objects = [self.data, first, second] if generated_first else [first, second, self.data]
                self._upload(objects)
                self.assertEqual(JSONData.objects.count(), 3)
                for payload in (first, second):
                    stored = JSONData.objects.get(data__identifier=payload["identifier"])
                    self.assertEqual(stored.data, payload)
                    self.assertEqual(stored.identifier_fingerprint, "")
                JSONData.objects.all().delete()

    def test_private_collision_extends_without_disclosing_or_changing_other_data(self):
        """
        Allocate globally without revealing another owner's private record
        """
        prefix = generate_data_identifier(self.data)
        private_data = dict(self.data, identifier=prefix, title="Confidential collision")
        private = JSONData.objects.create(
            owner=self.other, data=private_data, access_type="c",
        )

        response = self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 2)
        uploaded = JSONData.objects.exclude(pk=private.pk).get()
        self.assertEqual(uploaded.owner, self.owner)
        self.assertEqual(len(uploaded.data["identifier"]), 9)
        self.assertTrue(uploaded.data["identifier"].startswith(prefix))
        message = self._messages(response)
        self.assertNotIn(self.other.username, message)
        self.assertNotIn(private_data["title"], message)
        private.refresh_from_db()
        self.assertEqual(private.data, private_data)
        self.assertEqual(private.owner, self.other)
        self.assertEqual(private.access_type, "c")

    def test_null_and_blank_identifiers_are_generated(self):
        """
        Treat null and whitespace identifiers as absent rather than invalid
        """
        objects = []
        for index, value in enumerate((None, "", " \t\n")):
            objects.append(dict(self.data, identifier=value, title=f"Object {index}"))
        self._upload(objects)
        identifiers = list(JSONData.objects.values_list("data__identifier", flat=True))
        self.assertEqual(len(identifiers), 3)
        self.assertEqual(len(set(identifiers)), 3)
        for identifier in identifiers:
            self.assertRegex(identifier, r"^[0-9a-z]{8}$")

    def test_each_wrapped_object_gets_its_own_identifier(self):
        """
        Generate identifiers per object rather than for the enclosing file
        """
        second = dict(self.data, title="Different simulation")
        self._upload({"identifier": "file-wrapper", "data": [self.data, second]})
        identifiers = list(JSONData.objects.values_list("data__identifier", flat=True))
        self.assertEqual(len(identifiers), 2)
        self.assertEqual(len(set(identifiers)), 2)
        self.assertNotIn("file-wrapper", identifiers)

    def test_existing_text_identifier_is_preserved(self):
        """
        Keep an explicitly supplied identifier even for identical content
        """
        payload = dict(self.data, identifier="Experiment-A_01")
        self._upload(payload)
        self.assertEqual(JSONData.objects.get().data, payload)

    def test_reordered_keys_and_optional_fields_do_not_change_identifier(self):
        """
        Recognize the same required content despite JSON key order or notes
        """
        self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        reordered = dict(reversed(list(self.data.items())))
        reordered["units"] = dict(reversed(list(reordered["units"].items())))
        reordered["description"] = "A different optional description"
        response = self._upload(reordered)
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("already exists", message)
        self.assertIn("file-1.json data object 1", message)

    def test_zero_and_false_remain_part_of_the_hashed_content(self):
        """
        Keep meaningful zero and false values instead of cleaning them away
        """
        first = dict(self.data, RVE_continuity=False, RVE_size=[0, 1, 1])
        second = dict(first, RVE_continuity=True)
        third = dict(first, RVE_size=[1, 1])
        self._upload([first, second, third])
        self.assertEqual(JSONData.objects.count(), 3)
        self.assertEqual(len(set(JSONData.objects.values_list("data__identifier", flat=True))), 3)

    def test_repeated_generated_content_in_one_file_is_reported(self):
        """
        Save only the first occurrence and identify the duplicate object
        """
        response = self._upload([self.data, self.data])
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("partially successful", message)
        self.assertIn("file-1.json data object 2", message)
        self.assertIn("duplicated in this upload", message)

    def test_repeated_generated_content_across_files_is_reported(self):
        """
        Share the duplicate check across every file in a submission
        """
        response = self._upload(self.data, self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("file-2.json data object 1", message)
        self.assertIn("duplicated in this upload", message)

    def test_explicit_duplicate_identifiers_in_and_across_files_are_reported(self):
        """
        Reject repeated supplied identifiers without overwriting data
        """
        payload = dict(self.data, identifier="explicit-duplicate")
        response = self._upload([payload, payload], payload)
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("file-1.json data object 2", message)
        self.assertIn("file-2.json data object 1", message)

    def test_generated_identifier_checks_other_users_private_data(self):
        """
        Enforce global identifier uniqueness without disclosing private data
        """
        self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        stored = JSONData.objects.get()
        stored.owner = self.other
        stored.access_type = "c"
        stored.save()
        response = self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("already exists", message)
        self.assertNotIn(self.other.username, message)
        self.assertNotIn(str(stored.data["title"]), message)

    def test_generated_and_supplied_identifiers_share_the_same_namespace(self):
        """
        Prevent an explicit identifier from bypassing generated ID checks
        """
        self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        identifier = JSONData.objects.get().data["identifier"]
        JSONData.objects.all().delete()
        explicit = dict(self.data, identifier=identifier, title="Other simulation")
        response = self._upload([self.data, explicit])
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertIn("file-1.json data object 2", self._messages(response))

    def test_other_missing_fields_still_fail_without_blocking_valid_objects(self):
        """
        Keep mandatory metadata validation when identifier becomes optional
        """
        invalid = dict(self.data)
        invalid.pop("phase")
        response = self._upload([invalid, self.data])
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("Data object 1", message)
        self.assertIn("missing required field: phase", message)
        self.assertNotIn("missing required field: identifier", message)

    def test_malformed_identifiers_are_reported_instead_of_replaced(self):
        """
        Require supplied identifiers to be text without surrounding spaces
        """
        for identifier in ([], {}, 42, True, " padded "):
            with self.subTest(identifier=identifier):
                response = self._upload(dict(self.data, identifier=identifier))
                self.assertEqual(JSONData.objects.count(), 0)
                message = self._messages(response)
                self.assertIn("Data object 1", message)
                self.assertIn("identifier", message)
                self.assertIn("Please", message)
