import copy
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import JSONData
from .upload_services import canonical_json_size


class UploadIdentifierTests(TestCase):
    """
    Exercise identifier generation and conflicts through real uploads
    """

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
        self.assertRegex(identifier, r"^[0-9a-f]{64}$")
        self.assertEqual(stored.data, dict(self.data, identifier=identifier))
        self.assertNotIn("identifier", self.data)
        self.assertEqual(stored.size_bytes, canonical_json_size(stored.data))
        exported = self.client.get(reverse("json_data_export", args=[stored.pk]))
        self.assertEqual(json.loads(exported.content), stored.data)

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
            self.assertRegex(identifier, r"^[0-9a-f]{64}$")

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
