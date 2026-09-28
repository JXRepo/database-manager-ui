import json
from copy import deepcopy

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.dyn_api.metadata_compat import field_value

from .models import DataNotification, JSONData
from .upload_services import PreparedJSONData, UploadIdentifierConflict, canonical_json_size, save_prepared_json_data
from .upload_test_data import valid_upload_object, variant_field_names


class UploadCompatibilityTests(TestCase):
    """
    Exercise relaxed uploads through storage, access, search and export
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create isolated uploaders and viewers
        """
        cls.owner = User.objects.create_user(username="compat-owner")
        cls.viewer = User.objects.create_user(username="compat-viewer")

    def setUp(self):
        """
        Authenticate the local test uploader
        """
        self.client.force_login(self.owner)

    def upload(self, payload):
        """
        Submit one JSON file through the ordinary upload endpoint

        Parameters
        ----------
        payload : object
            Parsed content for the test file.

        Returns
        -------
        HttpResponse
            Upload result page.
        """
        file = SimpleUploadedFile("compat.json", json.dumps(payload).encode(), "application/json")
        return self.client.post(reverse("upload_json"), {"file": file}, follow=True)

    def test_relaxed_upload_supports_details_search_and_unchanged_json_export(self):
        """
        Use the recognized values across the platform and preserve original JSON
        """
        data = valid_upload_object(identifier="compatible-1", shared_with=[" ALL "])
        data["mechanical_BC"][0]["constraints"] = ["loaded", "free", "free"]
        data["mechanical_BC"][0]["loading_type"] = "force"
        data["mechanical_BC"][0]["applied_load"] = [{"magnitude": " 1.5\n"}]
        data["stress"]["equivalent_stress"] = ["0", "1.5"]
        data = variant_field_names(data)
        self.upload({"collection": {"record": data}})
        self.assertEqual(JSONData.objects.count(), 1)
        obj = JSONData.objects.get()
        self.assertEqual(obj.data, data)
        self.assertEqual(obj.size_bytes, canonical_json_size(data))
        self.assertEqual(obj.access_type, "all")
        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        self.assertContains(response, data["TITLE"])
        curves = response.context["plot_variables"]
        curve = next(item for item in curves if item["key"] == "stress.equivalent_stress")
        self.assertEqual(curve["values"], [0, 1.5])
        self.assertEqual(curve["unit"], "MPa")
        self.assertTrue(response.context["mechanical_bc_items"])
        response = self.client.get(reverse("mechanical_csv_export", args=[obj.pk]))
        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content).decode()
        self.assertIn("1.5", content)
        response = self.client.get(reverse("json_data_list"), {"software": "Solver", "phase": "Copper"})
        self.assertEqual(response.context["result_count"], 1)
        response = self.client.get(reverse("search"), {"identifier": "compatible-1"})
        self.assertContains(response, data["TITLE"])
        response = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(json.loads(response.content), data)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("json_data_detail", args=[obj.pk])).status_code, 200)

    def test_wrapped_values_work_in_upload_details_search_and_export(self):
        """
        Keep supplied wrapped identifiers and metadata while using recognized values
        """
        data = valid_upload_object(identifier=[["wrapped-upload"]], title=["Wrapped simulation"], shared_with=[[["ALL"]]])
        data["software"] = [[data["software"]]]
        data["phase"][0]["phase_name"] = ["Copper"]
        data["mechanical_BC"][0].update({
            "constraints": ["loaded", "free", "free"], "loading_type": ["force"],
            "applied_load": [[{"magnitude": [["1.5"]]}]],
        })
        data["stress"] = [{"equivalent_stress": [["1.5"]]}]
        data["total_strain"] = [{"equivalent_strain": [["0.01"]]}]
        data["units"] = [[{key: [value] for key, value in data["units"].items()}]]
        data["global_temperature"] = [["298"]]
        data = variant_field_names(data)
        self.upload(data)
        self.assertEqual(JSONData.objects.count(), 1)
        obj = JSONData.objects.get()
        self.assertEqual(obj.data, data)
        self.assertEqual(field_value(obj.data, "identifier"), "wrapped-upload")
        self.assertEqual(obj.size_bytes, canonical_json_size(data))
        self.assertEqual(obj.access_type, "all")
        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        self.assertEqual(response.context["metadata"]["title"], "Wrapped simulation")
        curve = next(item for item in response.context["plot_variables"] if item["key"] == "stress.equivalent_stress")
        self.assertEqual(curve["values"], [1.5])
        self.assertEqual(curve["unit"], "MPa")
        self.assertTrue(response.context["mechanical_bc_items"])
        response = self.client.get(reverse("mechanical_csv_export", args=[obj.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("1.5", b"".join(response.streaming_content).decode())
        response = self.client.get(reverse("json_data_list"), {"software": "Solver", "phase": "Copper"})
        self.assertEqual(response.context["result_count"], 1)
        response = self.client.get(reverse("search"), {
            "identifier": "wrapped-upload", "condition_field": "global_temperature",
            "condition_operator": "eq", "condition_value": "298",
        })
        self.assertEqual(response.context["result_count"], 1)
        response = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(json.loads(response.content), data)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("json_data_detail", args=[obj.pk])).status_code, 200)

    def test_wrapped_identifiers_cannot_bypass_duplicate_checks(self):
        """
        Detect stored, same-file and final transaction identifier conflicts
        """
        self.upload(valid_upload_object(identifier=[["repeat-wrapped"]]))
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertContains(self.upload(valid_upload_object(identifier="repeat-wrapped")), "already exists")
        self.assertContains(self.upload(valid_upload_object(identifier=["repeat-wrapped"])), "already exists")
        response = self.upload([valid_upload_object(identifier="same-file"),
                                valid_upload_object(identifier=[["same-file"]])])
        self.assertContains(response, "more than once")
        candidate_data = valid_upload_object(identifier=["repeat-wrapped"])
        candidate = PreparedJSONData(data=candidate_data, access_type="c", shared_users=(),
                                     size_bytes=canonical_json_size(candidate_data))
        with self.assertRaises(UploadIdentifierConflict):
            save_prepared_json_data(self.owner, [candidate])
        self.assertEqual(JSONData.objects.count(), 1)

    def test_wrapped_empty_identifier_is_filled_without_changing_other_data(self):
        """
        Generate an identifier inside its original wrappers and deduplicate content
        """
        data = valid_upload_object(identifier=[[None]], title=["Wrapped generated ID"])
        self.upload(data)
        self.assertEqual(JSONData.objects.count(), 1)
        obj = JSONData.objects.get()
        identifier = field_value(obj.data, "identifier")
        self.assertEqual(identifier, "8ccf8eb1")
        expected = deepcopy(data)
        expected["identifier"] = [[identifier]]
        self.assertEqual(obj.data, expected)
        self.assertEqual(obj.size_bytes, canonical_json_size(expected))
        self.assertContains(self.upload(data), "already exists")
        self.assertEqual(JSONData.objects.count(), 1)

    def test_wrapped_sharing_preserves_explicit_permissions(self):
        """
        Recognize wrapped tokens and usernames without broadening private access
        """
        for index, sharing in enumerate(([[[" ALL "]]], [[{"Access-Type": [[" ALL "]]}]], [{"all": [[True]]}])):
            with self.subTest(sharing=sharing):
                self.upload(valid_upload_object(identifier=f"wrapped-public-{index}", shared_with=sharing))
                self.assertEqual(JSONData.objects.filter(access_type="all").count(), index + 1)
        data = valid_upload_object(identifier=["wrapped-private"], title=["Private simulation"],
                                   shared_with=[[{"username": [[self.viewer.username]]}]])
        self.upload(data)
        obj = JSONData.objects.get(access_type="c")
        self.assertEqual(obj.data, data)
        self.assertEqual(list(obj.shared_users.all()), [self.viewer])
        notification = DataNotification.objects.get()
        self.assertEqual(notification.display_title, "wrapped-private")
        self.assertEqual(notification.display_name, "Private simulation")
        other = User.objects.create_user(username="compat-other")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("json_data_detail", args=[obj.pk])).status_code, 404)

    def test_wrappers_cannot_hide_ambiguous_sharing_or_required_errors(self):
        """
        Reject the whole file if wrapped content is empty or permissions conflict
        """
        for index, sharing in enumerate(([["all", "c"]], [[["not all"]]],
                                         [{"note": [["all"]]}], [{"all": [False]}],
                                         [{"access_type": ["all", "c"]}],
                                         [{"access_type": ["c"], "Access-Type": [["all"]]}])):
            with self.subTest(sharing=sharing):
                self.upload(valid_upload_object(identifier=f"ambiguous-wrapped-{index}", shared_with=sharing))
                self.assertEqual(JSONData.objects.count(), 0)
        response = self.upload([valid_upload_object(identifier="neighbor"),
                                valid_upload_object(identifier=["bad-required"], title=[[""]])])
        self.assertContains(response, "Empty values")
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertEqual(DataNotification.objects.count(), 0)

    def test_identifier_aliases_do_not_bypass_existing_or_batch_duplicates(self):
        """
        Treat formatted identifier field names as the same lookup key
        """
        first = variant_field_names(valid_upload_object(identifier="repeat-id"))
        self.upload(first)
        self.assertEqual(JSONData.objects.count(), 1)
        response = self.upload(valid_upload_object(identifier="repeat-id"))
        self.assertContains(response, "already exists")
        self.assertEqual(JSONData.objects.count(), 1)
        batch = [valid_upload_object(identifier="batch-id"),
                 variant_field_names(valid_upload_object(identifier="batch-id"))]
        response = self.upload(batch)
        self.assertContains(response, "more than once")
        self.assertEqual(JSONData.objects.count(), 1)

    def test_preset_search_uses_the_same_separator_matching_as_upload(self):
        """
        Find accepted dotted field spellings through scientific preset filters
        """
        data = valid_upload_object(identifier="dotted-fields")
        boundary = data.pop("mechanical_BC")[0]
        boundary["Loading.Type"] = "force"
        data["Mechanical.BC"] = [boundary]
        self.upload(data)
        self.assertEqual(JSONData.objects.count(), 1)
        response = self.client.get(reverse("search"), {
            "condition_field": "loading_type", "condition_operator": "words", "condition_value": "force",
        })
        self.assertEqual(response.context["result_count"], 1)

    def test_one_conflicting_record_rejects_the_entire_file(self):
        """
        Keep file atomicity when normalized aliases disagree
        """
        first = valid_upload_object(identifier="first")
        second = valid_upload_object(identifier="second")
        second["Date"] = "1900-01-01"
        response = self.upload([first, second])
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertContains(response, "Conflicting fields")

    def test_invalid_unicode_in_a_conflicting_alias_still_returns_feedback(self):
        """
        Keep malformed field text from breaking the rendered error report
        """
        data = valid_upload_object(identifier="bad-alias")
        data["da\ud800te"] = "1900-01-01"
        response = self.upload(data)
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertContains(response, "invalid Unicode")
        self.assertContains(response, "Conflicting fields")

    def test_public_word_inside_other_text_never_grants_access(self):
        """
        Reject ambiguous sharing and retain explicit private user permissions
        """
        for index, sharing in enumerate((["small"], ["not all"], [{"note": "all"}],
                                         [{"username": "all"}], [{"all": False}])):
            with self.subTest(sharing=sharing):
                self.upload(valid_upload_object(identifier=f"unsafe-{index}", shared_with=sharing))
                self.assertEqual(JSONData.objects.count(), 0)
        data = variant_field_names(valid_upload_object(
            identifier="private-share", shared_with=[{"username": self.viewer.username}],
        ))
        self.upload(data)
        self.assertEqual(JSONData.objects.count(), 1)
        obj = JSONData.objects.get()
        self.assertEqual(obj.access_type, "c")
        self.assertEqual(list(obj.shared_users.all()), [self.viewer])
        self.assertEqual(DataNotification.objects.get().display_title, "private-share")

    def test_a_user_named_all_remains_an_explicit_private_share(self):
        """
        Keep usernames separate from permission tokens even when their text matches
        """
        recipient = User.objects.create_user(username="all")
        self.upload(valid_upload_object(identifier="share-with-all-user", shared_with=[{"username": "all"}]))
        obj = JSONData.objects.get()
        self.assertEqual(obj.access_type, "c")
        self.assertEqual(list(obj.shared_users.all()), [recipient])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("json_data_detail", args=[obj.pk])).status_code, 404)

    def test_nested_permission_alias_conflicts_reject_all_neighbors(self):
        """
        Reject contradictory public and private aliases before any file is saved
        """
        ambiguous = valid_upload_object(identifier="ambiguous", shared_with=[{
            "access_type": "c", "Access-Type": "all",
        }])
        response = self.upload([valid_upload_object(identifier="good"), ambiguous])
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertContains(response, "Conflicting fields")

    def test_final_save_rechecks_formatted_identifiers(self):
        """
        Prevent a late duplicate from bypassing the transactional check
        """
        data = variant_field_names(valid_upload_object(identifier="late-conflict"))
        candidate = PreparedJSONData(data=data, access_type="c", shared_users=(), size_bytes=canonical_json_size(data))
        JSONData.objects.create(owner=self.owner, data=valid_upload_object(identifier="late-conflict"))
        with self.assertRaises(UploadIdentifierConflict):
            save_prepared_json_data(self.owner, [candidate])
        self.assertEqual(JSONData.objects.count(), 1)

    def test_auto_identifier_handles_aliases_without_changing_other_values(self):
        """
        Accept alternative spellings while hashing the raw JSON as Ronak does
        """
        original = valid_upload_object()
        data = variant_field_names(original)
        self.upload(data)
        self.assertEqual(JSONData.objects.count(), 1)
        obj = JSONData.objects.get()
        expected = deepcopy(data)
        expected["identifier"] = "d41d8cd9"
        self.assertEqual(obj.data, expected)
        self.assertContains(self.upload(data), "already exists")
        self.assertEqual(JSONData.objects.count(), 1)
        self.upload(original)
        self.assertEqual(JSONData.objects.count(), 2)
        self.assertEqual(JSONData.objects.exclude(pk=obj.pk).get().data["identifier"], "49793b40")

    def test_cpu_alias_keeps_raw_export_and_ronaks_identifier_calculation(self):
        """
        Accept either processor name without changing Ronak's exact field lookup
        """
        original = valid_upload_object()
        data = deepcopy(original)
        data["CPU_specifications"] = data.pop("processor_specifications")
        self.upload(data)
        self.assertEqual(JSONData.objects.count(), 1)
        obj = JSONData.objects.get()
        expected = dict(data, identifier="359e929d")
        self.assertEqual(obj.data, expected)
        response = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(json.loads(response.content), expected)
        self.assertContains(self.upload(data), "already exists")
        self.assertEqual(JSONData.objects.count(), 1)
        self.upload(original)
        self.assertEqual(JSONData.objects.count(), 2)
        self.assertEqual(JSONData.objects.exclude(pk=obj.pk).get().data["identifier"], "49793b40")
