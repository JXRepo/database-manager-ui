import json
from copy import deepcopy

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import JSONData
from .upload_test_data import valid_upload_object
from .views import _inspect_upload_file


class UploadUnwrapTests(TestCase):
    """
    Recognize record boundaries while preserving incomplete entries and order
    """

    def setUp(self):
        """
        Create an isolated uploader and two distinct complete objects
        """
        self.owner = User.objects.create_user("unwrap-owner")
        self.client.force_login(self.owner)
        self.first = valid_upload_object(identifier="first", title="First")
        self.second = valid_upload_object(identifier="second", title="Second")

    def upload(self, payload):
        """
        Exercise the normal upload path and rendered error report

        Parameters
        ----------
        payload : object
            JSON payload to upload.

        Returns
        -------
        HttpResponse
            Upload page after the form redirect.
        """
        file = SimpleUploadedFile("records.json", json.dumps(payload).encode())
        return self.client.post(reverse("upload_json"), {"file": file}, follow=True)

    def test_identifier_mapping_saves_individual_records_in_order(self):
        """
        Accept Ronak's dictionary shape without editing the inner records
        """
        self.upload({"first": self.first, "second": self.second})
        self.assertEqual(list(JSONData.objects.order_by("pk").values_list("data", flat=True)),
                         [self.first, self.second])

    def test_unfamiliar_nested_wrappers_and_lists_are_unwrapped(self):
        """
        Find objects without requiring an enumerated wrapper field name
        """
        self.upload({"experiment": {"runs": [{"first": self.first}, {"second": self.second}]}})
        self.assertEqual(JSONData.objects.count(), 2)

    def test_descriptive_wrapper_metadata_does_not_hide_its_records(self):
        """
        Distinguish a collection title from an incomplete simulation record
        """
        self.upload({"title": "Experiment collection", "description": "Two runs",
                     "experiment": {"runs": [self.first, self.second]}})
        self.assertEqual(JSONData.objects.count(), 2)

    def test_descriptive_keyword_variants_do_not_become_extra_records(self):
        """
        Count records consistently when a collection uses a descriptive title alias
        """
        self.upload({"collection_title": "Experiment collection", "runs": [self.first, self.second]})
        self.assertEqual(list(JSONData.objects.order_by("pk").values_list("data", flat=True)),
                         [self.first, self.second])

    def test_incomplete_descriptive_record_is_not_split_into_its_values(self):
        """
        Report missing fields on the object instead of treating creators as records
        """
        response = self.upload({"record": {"simulation_title": "Incomplete",
                                          "creator_primary": ["Researcher"],
                                          "software_primary": "Solver"}})
        self.assertFalse(JSONData.objects.exists())
        self.assertContains(response, "Object 1")
        self.assertNotContains(response, "Object 2")
        self.assertContains(response, "Incomplete")

    def test_thirty_invalid_members_prevent_all_one_hundred_saves(self):
        """
        Collect all thirty errors while preserving the whole file save boundary
        """
        records = {f"record-{index}": valid_upload_object(identifier=f"record-{index}", title=f"Run {index}")
                   for index in range(100)}
        for index in range(70, 100):
            records[f"record-{index}"]["units"]["Stress"] = None
        response = self.upload(records)
        self.assertFalse(JSONData.objects.exists())
        self.assertContains(response, "30 data objects need changes")
        self.assertContains(response, "data-upload-object", count=30)
        self.assertContains(response, "units.Stress", count=31)

    def test_incomplete_mapping_member_is_not_silently_dropped(self):
        """
        Reject the whole file and identify its incomplete sibling
        """
        response = self.upload({"first": self.first, "second": {"title": "Incomplete"}})
        self.assertFalse(JSONData.objects.exists())
        self.assertContains(response, "Incomplete")
        self.assertContains(response, "Object 2")
        self.assertContains(response, "units")

    def test_scalar_mapping_member_cannot_disappear(self):
        """
        Keep invalid siblings visible rather than importing a partial map
        """
        response = self.upload({"first": self.first, "broken": 42})
        self.assertFalse(JSONData.objects.exists())
        self.assertContains(response, "Object 2")

    def test_complete_object_keeps_nested_metadata_even_when_named_data(self):
        """
        Stop at a record boundary and preserve its complete original content
        """
        self.first["data"] = [deepcopy(self.second)]
        self.upload(self.first)
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, self.first)

    @override_settings(PILOT_MAX_UPLOAD_OBJECTS=1)
    def test_mapping_objects_participate_in_batch_precheck(self):
        """
        Reject an over limit mapping before any record is saved
        """
        response = self.upload({"first": self.first, "second": self.second})
        self.assertFalse(JSONData.objects.exists())
        self.assertContains(response, "maximum number")

    def test_precheck_retains_only_paths_not_parsed_records(self):
        """
        Keep batch inspection memory bounded independently of record size
        """
        file = SimpleUploadedFile("records.json", json.dumps({"group": [self.first, self.second]}).encode())
        report = {"issues": {}}
        count, paths = _inspect_upload_file(file, report)
        self.assertEqual(count, 2)
        self.assertEqual(paths, [("group", 0), ("group", 1)])

    def test_invalid_unicode_in_a_wrapper_key_returns_feedback(self):
        """
        Reject invalid source text without letting its location break the response
        """
        self.first["units"] = {}
        response = self.upload({"\ud800": self.first})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JSONData.objects.exists())
        self.assertContains(response, "Invalid text encoding")
