import copy
import json

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .upload_test_data import valid_upload_object
from .models import JSONData
from .upload_services import canonical_json_size, generate_data_identifier


class UploadIdentifierTests(TestCase):
    """
    Exercise identifier generation and conflicts through real uploads
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create synthetic metadata and two isolated upload owners
        """
        cls.owner = User.objects.create_user(username="identifier-owner", password="password")
        cls.other = User.objects.create_user(username="identifier-other", password="password")
        cls.example = valid_upload_object(identifier="example")

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
        self.assertEqual(identifier, "49793b40")
        self.assertEqual(stored.data, dict(self.data, identifier=identifier))
        self.assertNotIn("identifier", self.data)
        self.assertEqual(stored.identifier_fingerprint, "")
        self.assertEqual(stored.size_bytes, canonical_json_size(stored.data))
        exported = self.client.get(reverse("json_data_export", args=[stored.pk]))
        self.assertEqual(json.loads(exported.content), stored.data)
        self.assertNotIn("identifier_fingerprint", json.loads(exported.content))

    def test_database_collision_is_reported_without_extending_identifier(self):
        """
        Preserve the existing object when distinct content generates its identifier
        """
        original = dict(self.data, identifier="49793b40", title="Existing different object")
        stored = JSONData.objects.create(
            owner=self.owner,
            data=original,
        )

        response = self._upload(self.data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 1)
        stored.refresh_from_db()
        self.assertEqual(stored.data, original)
        self.assertEqual(stored.owner, self.owner)
        self.assertIn("already exists", self._messages(response))

    def test_numeric_looking_identifiers_stay_text_and_block_repeat_uploads(self):
        """
        Preserve numeric and exponent shaped identifiers during digest lookup
        """
        for title, identifier in (("Numeric identifier fixture 70", "74846891"),
                                  ("Numeric identifier fixture 1763", "9e619007")):
            with self.subTest(identifier=identifier):
                data = dict(self.data, title=title)
                self._upload(data)
                self.assertEqual(JSONData.objects.get().data["identifier"], identifier)
                response = self._upload(data)
                self.assertEqual(JSONData.objects.count(), 1)
                self.assertEqual(JSONData.objects.get().data["identifier"], identifier)
                self.assertIn("already exists", self._messages(response))
                JSONData.objects.all().delete()

    def test_supplied_identifier_collision_in_batch_rejects_the_file(self):
        """
        Reject a generated identifier that repeats an earlier supplied identifier
        """
        prefix = generate_data_identifier(self.data)
        explicit = dict(self.data, identifier=prefix, title="Distinct supplied object")

        response = self._upload([explicit, self.data])

        self.assertEqual(JSONData.objects.count(), 0)
        self.assertIn("used more than once", self._messages(response))

    def test_supplied_identifier_collision_across_files_preserves_the_first_file(self):
        """
        Reserve earlier supplied identifiers across files in one submission
        """
        prefix = generate_data_identifier(self.data)
        explicit = dict(self.data, identifier=prefix, title="Distinct file object")

        response = self._upload(explicit, self.data)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, explicit)
        self.assertIn("used more than once", self._messages(response))

    def test_retry_after_conflicting_record_is_deleted_keeps_the_same_identifier(self):
        """
        Use the same eight characters when a previously occupied identifier is free
        """
        prefix = generate_data_identifier(self.data)
        occupier = JSONData.objects.create(
            owner=self.owner,
            data=dict(self.data, identifier=prefix, title="Temporary occupier"),
        )
        self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        occupier.delete()

        self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, dict(self.data, identifier=prefix))

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

    def test_reimported_identifier_blocks_a_repeat_generated_upload(self):
        """
        Keep duplicate detection after exporting and reimporting a generated ID
        """
        self._upload(self.data)
        stored = JSONData.objects.get()
        exported = self.client.get(reverse("json_data_export", args=[stored.pk]))
        payload = json.loads(exported.content)
        self.assertEqual(payload["identifier"], "49793b40")
        JSONData.objects.all().delete()
        self._upload(payload)
        self.assertEqual(JSONData.objects.get().identifier_fingerprint, "")

        response = self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, payload)
        self.assertIn("already exists", self._messages(response))

    def test_legacy_identifier_is_retained_without_affecting_new_generation(self):
        """
        Leave historical records untouched while new IDs follow Ronak's template
        """
        legacy = dict(self.data, identifier="684a6b9eaf174e77e12ab42a7243ba6509079ee959a3ac7f41562d839ec8e89f")
        stored = JSONData.objects.create(owner=self.owner, data=legacy)

        self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 2)
        stored.refresh_from_db()
        self.assertEqual(stored.data, legacy)
        self.assertEqual(stored.identifier_fingerprint, "")
        self.assertEqual(JSONData.objects.exclude(pk=stored.pk).get().data["identifier"], "49793b40")

    def test_supplied_ronak_identifier_and_generated_identifier_conflict_in_either_order(self):
        """
        Reject the whole file when a supplied ID matches the template calculation
        """
        supplied = dict(self.data, identifier="49793b40")
        for supplied_first in (True, False):
            with self.subTest(supplied_first=supplied_first):
                objects = [supplied, self.data] if supplied_first else [self.data, supplied]
                response = self._upload(objects)
                self.assertEqual(JSONData.objects.count(), 0)
                message = self._messages(response)
                self.assertNotIn("partially successful", message)
                self.assertIn("file-1.json", message)
                self.assertIn("Object 2 in this file", message)
                self.assertIn("used more than once in this upload", message)

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

    def test_private_collision_is_reported_without_disclosing_or_changing_other_data(self):
        """
        Reject duplicate identifiers without revealing another owner's private record
        """
        prefix = generate_data_identifier(self.data)
        private_data = dict(self.data, identifier=prefix, title="Confidential collision")
        private = JSONData.objects.create(
            owner=self.other, data=private_data, access_type="c",
        )

        response = self._upload(self.data)

        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("already exists", message)
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
            self.assertRegex(identifier, r"^[0-9a-f]{8}$")

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
        self.assertIn("file-1.json", message)
        self.assertIn("Object 1 in this file", message)

    def test_zero_and_false_remain_in_saved_json_after_template_hashing(self):
        """
        Preserve meaningful zero and false values in storage and JSON exports
        """
        first = dict(self.data, RVE_continuity=False, RVE_size=[0, 1, 1])
        second = dict(first, RVE_continuity=True)
        self._upload([first, second])
        self.assertEqual(JSONData.objects.count(), 2)
        self.assertEqual(JSONData.objects.get(data__identifier="86e64d35").data,
                         dict(first, identifier="86e64d35"))
        self.assertEqual(JSONData.objects.get(data__identifier="14c819d5").data,
                         dict(second, identifier="14c819d5"))

    def test_repeated_generated_content_in_one_file_is_reported(self):
        """
        Reject every object in the file and identify its repeated content
        """
        response = self._upload([self.data, self.data])
        self.assertEqual(JSONData.objects.count(), 0)
        message = self._messages(response)
        self.assertNotIn("partially successful", message)
        self.assertIn("file-1.json", message)
        self.assertIn("Object 2 in this file", message)
        self.assertIn("used more than once in this upload", message)

    def test_explicit_duplicate_identifiers_in_one_file_reject_the_whole_file(self):
        """
        Save neither supplied object when their identifiers repeat in one file
        """
        first = dict(self.data, identifier="explicit-duplicate", title="First supplied object")
        second = dict(self.data, identifier="explicit-duplicate", title="Second supplied object")

        response = self._upload([first, second])

        self.assertEqual(JSONData.objects.count(), 0)
        message = self._messages(response)
        self.assertNotIn("partially successful", message)
        self.assertIn("file-1.json", message)
        self.assertIn("Object 2 in this file", message)
        self.assertIn("Second supplied object", message)
        self.assertIn('data-upload-category="duplicate_identifier"', message)

    def test_repeated_generated_content_across_files_is_reported(self):
        """
        Keep the earlier saved file when a later file repeats its content
        """
        response = self._upload(self.data, self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("file-2.json", message)
        self.assertIn("Object 1 in this file", message)
        self.assertIn('data-upload-category="duplicate_identifier"', message)
        self.assertEqual(JSONData.objects.get().identifier_fingerprint, "")

    def test_explicit_duplicates_reject_the_file_without_reserving_ids_for_later_files(self):
        """
        Reject a file with repeated identifiers while allowing the next valid file
        """
        payload = dict(self.data, identifier="explicit-duplicate")
        response = self._upload([payload, payload], payload)
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, payload)
        message = self._messages(response)
        self.assertIn("file-1.json", message)
        self.assertIn("Object 2 in this file", message)
        self.assertIn("file-2.json", message)
        self.assertIn('data-upload-file-status="uploaded"', message)
        self.assertNotIn('data-upload-file-status="skipped"', message)
        self.assertNotIn("Object 1 in this file", message)

    def test_explicit_duplicate_across_files_preserves_the_earlier_upload(self):
        """
        Keep the first file unchanged when the next file repeats its identifier
        """
        first = dict(self.data, identifier="explicit-duplicate", title="First file object")
        second = dict(first, title="Conflicting second file object")

        response = self._upload(first, second)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, first)
        message = self._messages(response)
        self.assertIn("file-2.json", message)
        self.assertIn("Conflicting second file object", message)
        self.assertIn('data-upload-category="duplicate_identifier"', message)

    def test_generated_identifier_checks_other_users_private_data(self):
        """
        Enforce global identifier uniqueness without disclosing private data
        """
        self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        stored = JSONData.objects.get()
        stored.owner = self.other
        stored.access_type = "c"
        stored.data["private_note"] = "Confidential metadata from another owner"
        stored.save()
        response = self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        message = self._messages(response)
        self.assertIn("already exists", message)
        self.assertNotIn(self.other.username, message)
        self.assertNotIn(stored.data["private_note"], message)

    def test_generated_and_supplied_identifiers_share_the_same_namespace(self):
        """
        Reject the whole file when a supplied identifier repeats a generated one
        """
        self._upload(self.data)
        self.assertEqual(JSONData.objects.count(), 1)
        identifier = JSONData.objects.get().data["identifier"]
        JSONData.objects.all().delete()
        explicit = dict(self.data, identifier=identifier, title="Other simulation")
        response = self._upload([self.data, explicit])
        self.assertEqual(JSONData.objects.count(), 0)
        message = self._messages(response)
        self.assertIn("file-1.json", message)
        self.assertIn("Object 2 in this file", message)

    def test_other_missing_fields_reject_all_objects_in_the_file(self):
        """
        Reject valid neighbors when required metadata is missing in the file
        """
        invalid = dict(self.data)
        invalid.pop("phase")
        response = self._upload([invalid, self.data])
        self.assertEqual(JSONData.objects.count(), 0)
        message = self._messages(response)
        self.assertIn("Object 1 in this file", message)
        self.assertIn('data-upload-category="missing_required"', message)
        self.assertIn("<code>phase</code>", message)
        self.assertNotIn("<code>identifier</code>", message)

    def test_malformed_identifiers_are_reported_instead_of_replaced(self):
        """
        Require supplied identifiers to be text without surrounding spaces
        """
        for identifier in ([], {}, 42, True, " padded "):
            with self.subTest(identifier=identifier):
                response = self._upload(dict(self.data, identifier=identifier))
                self.assertEqual(JSONData.objects.count(), 0)
                message = self._messages(response)
                self.assertIn("Object 1 in this file", message)
                self.assertIn("identifier", message)
                self.assertIn('data-upload-category="invalid_identifier"', message)
                self.assertIn("data-upload-guidance", message)
