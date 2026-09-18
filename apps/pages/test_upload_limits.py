import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import DataNotification, JSONData
from .rate_limits import RateLimitDecision
from .upload_services import (
    PreparedJSONData,
    UploadIdentifierConflict,
    UploadQuotaExceeded,
    UploadResourceLimitError,
    canonical_json_size,
    save_prepared_json_data,
    validate_json_depth,
    validate_upload_files,
)


class UploadServiceBoundaryTests(TestCase):
    """
    Test upload service boundaries independently from the upload form
    """

    def _file_with_size(self, name, size):
        """
        Build a real uploaded file with an exact byte size
        """
        return SimpleUploadedFile(
            name,
            b"x" * size,
            content_type="application/json",
        )

    def _nested_containers(self, depth):
        """
        Build a value with an exact number of nested list containers
        """
        value = 0

        for _index in range(depth):
            value = [value]

        return value

    @override_settings(PILOT_MAX_UPLOAD_FILES=5)
    def test_file_count_accepts_five_files(self):
        """
        Five files remain inside the configured request limit
        """
        files = []

        for index in range(5):
            files.append(self._file_with_size(f"{index}.json", 1))

        validate_upload_files(files)

    @override_settings(PILOT_MAX_UPLOAD_FILES=5)
    def test_file_count_rejects_six_files(self):
        """
        A sixth file exceeds the configured request limit
        """
        files = []

        for index in range(6):
            files.append(self._file_with_size(f"{index}.json", 1))

        with self.assertRaises(UploadResourceLimitError):
            validate_upload_files(files)

    @override_settings(PILOT_MAX_UPLOAD_FILE_BYTES=10 * 1024 * 1024)
    def test_file_size_accepts_exactly_ten_mebibytes(self):
        """
        A file at exactly ten mebibytes remains inside the limit
        """
        uploaded_file = self._file_with_size("exact.json", 10 * 1024 * 1024)

        validate_upload_files([uploaded_file])

    @override_settings(PILOT_MAX_UPLOAD_FILE_BYTES=10 * 1024 * 1024)
    def test_file_size_rejects_one_byte_over_ten_mebibytes(self):
        """
        One byte above ten mebibytes exceeds the per file limit
        """
        uploaded_file = self._file_with_size(
            "over.json",
            (10 * 1024 * 1024) + 1,
        )

        with self.assertRaises(UploadResourceLimitError):
            validate_upload_files([uploaded_file])

    @override_settings(
        PILOT_MAX_UPLOAD_FILE_BYTES=10 * 1024 * 1024,
        PILOT_MAX_UPLOAD_REQUEST_BYTES=25 * 1024 * 1024,
    )
    def test_request_size_accepts_exactly_twenty_five_mebibytes(self):
        """
        Three files totalling exactly twenty five mebibytes are accepted
        """
        files = [
            self._file_with_size("first.json", 10 * 1024 * 1024),
            self._file_with_size("second.json", 10 * 1024 * 1024),
            self._file_with_size("third.json", 5 * 1024 * 1024),
        ]

        validate_upload_files(files)

    @override_settings(
        PILOT_MAX_UPLOAD_FILE_BYTES=10 * 1024 * 1024,
        PILOT_MAX_UPLOAD_REQUEST_BYTES=25 * 1024 * 1024,
    )
    def test_request_size_rejects_one_byte_over_twenty_five_mebibytes(self):
        """
        One byte above twenty five mebibytes exceeds the request limit
        """
        files = [
            self._file_with_size("first.json", 10 * 1024 * 1024),
            self._file_with_size("second.json", 10 * 1024 * 1024),
            self._file_with_size("third.json", (5 * 1024 * 1024) + 1),
        ]

        with self.assertRaises(UploadResourceLimitError):
            validate_upload_files(files)

    def test_canonical_json_size_uses_compact_unicode_utf8(self):
        """
        Stored size uses compact JSON and the two UTF8 bytes for an umlaut
        """
        self.assertEqual(canonical_json_size({"label": "ä"}), 14)

    def test_canonical_json_size_rejects_lone_surrogate_value(self):
        """
        A lone surrogate value becomes a safe resource error
        """
        try:
            canonical_json_size({"label": "\ud800"})
        except Exception as error:
            self.assertIsInstance(error, UploadResourceLimitError)
            self.assertEqual(
                str(error),
                "Uploaded JSON contains invalid Unicode text.",
            )
        else:
            self.fail("Lone surrogate value was accepted")

    def test_canonical_json_size_rejects_lone_surrogate_key(self):
        """
        A lone surrogate key becomes a safe resource error
        """
        try:
            canonical_json_size({"\ud800": "value"})
        except Exception as error:
            self.assertIsInstance(error, UploadResourceLimitError)
            self.assertEqual(
                str(error),
                "Uploaded JSON contains invalid Unicode text.",
            )
        else:
            self.fail("Lone surrogate key was accepted")

    @override_settings(PILOT_MAX_JSON_DEPTH=100)
    def test_json_depth_accepts_exactly_one_hundred_containers(self):
        """
        One hundred nested containers remain inside the depth limit
        """
        validate_json_depth(self._nested_containers(100))

    @override_settings(PILOT_MAX_JSON_DEPTH=100)
    def test_json_depth_rejects_one_hundred_and_one_containers(self):
        """
        A one hundred and first container exceeds the depth limit
        """
        with self.assertRaises(UploadResourceLimitError):
            validate_json_depth(self._nested_containers(101))

    def test_json_depth_rejects_nonfinite_numbers(self):
        """
        Nonfinite JSON numbers are rejected as request resource failures
        """
        values = [float("nan"), float("inf"), float("-inf")]

        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(UploadResourceLimitError):
                    validate_json_depth({"value": value})


class PreparedUploadSaveTests(TestCase):
    """
    Test persisted size accounting, live quota, and atomic save behavior
    """

    def setUp(self):
        """
        Create the owner and share recipient used by save tests
        """
        self.owner = User.objects.create_user(
            username="quota-owner",
            password="password",
        )
        self.recipient = User.objects.create_user(
            username="quota-recipient",
            password="password",
        )

    def _prepared(self, identifier, size_bytes=1, shared_users=()):
        """
        Build one prepared object with explicit accounting inputs
        """
        return PreparedJSONData(
            data={"identifier": identifier},
            access_type="c",
            shared_users=shared_users,
            size_bytes=size_bytes,
        )

    def test_save_persists_prepared_compact_size(self):
        """
        The exact prepared byte size is stored with the JSON object
        """
        prepared = self._prepared("sized", size_bytes=17)

        saved_objects = save_prepared_json_data(self.owner, [prepared])

        self.assertEqual(len(saved_objects), 1)
        self.assertEqual(saved_objects[0].size_bytes, 17)

    @override_settings(PILOT_MAX_USER_JSON_BYTES=50 * 1024 * 1024)
    def test_quota_accepts_exactly_fifty_mebibytes(self):
        """
        An object reaching exactly fifty mebibytes remains inside quota
        """
        prepared = self._prepared(
            "exact-quota",
            size_bytes=50 * 1024 * 1024,
        )

        saved_objects = save_prepared_json_data(self.owner, [prepared])

        self.assertEqual(len(saved_objects), 1)
        self.assertEqual(saved_objects[0].size_bytes, 50 * 1024 * 1024)

    @override_settings(PILOT_MAX_USER_JSON_BYTES=50 * 1024 * 1024)
    def test_quota_rejects_bytes_beyond_fifty_mebibytes(self):
        """
        Live stored bytes at quota leave no room for another object
        """
        JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "existing"},
            size_bytes=50 * 1024 * 1024,
        )

        with self.assertRaises(UploadQuotaExceeded):
            save_prepared_json_data(self.owner, [self._prepared("over-quota")])

        self.assertEqual(JSONData.objects.count(), 1)

    @override_settings(PILOT_MAX_USER_JSON_BYTES=50 * 1024 * 1024)
    def test_deleting_data_frees_live_quota(self):
        """
        Removing stored data immediately makes its accounted bytes available
        """
        existing = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "existing"},
            size_bytes=50 * 1024 * 1024,
        )
        prepared = self._prepared("after-delete")

        with self.assertRaises(UploadQuotaExceeded):
            save_prepared_json_data(self.owner, [prepared])

        existing.delete()
        saved_objects = save_prepared_json_data(self.owner, [prepared])

        self.assertEqual(len(saved_objects), 1)
        self.assertTrue(
            JSONData.objects.filter(data__identifier="after-delete").exists()
        )

    def test_notification_failure_rolls_back_the_whole_prepared_batch(self):
        """
        An exception while notifying recipients rolls back every new row
        """
        objects = [
            self._prepared("first"),
            self._prepared(
                "second",
                shared_users=(self.recipient,),
            ),
        ]

        with patch(
            "apps.pages.upload_services.DataNotification.objects.create",
            side_effect=RuntimeError("notification failed"),
        ):
            with self.assertRaises(RuntimeError):
                save_prepared_json_data(self.owner, objects)

        self.assertEqual(JSONData.objects.count(), 0)
        self.assertEqual(DataNotification.objects.count(), 0)

    def test_long_unicode_upload_notifications_fit_the_message_field(self):
        """
        Long Unicode identifiers do not break a shared upload batch
        """
        first_identifier = ("材料" * 200) + "一"
        second_identifier = ("材料" * 200) + "二"
        objects = [
            self._prepared(
                first_identifier,
                shared_users=(self.recipient,),
            ),
            self._prepared(
                second_identifier,
                shared_users=(self.recipient,),
            ),
        ]

        saved_objects = save_prepared_json_data(self.owner, objects)

        self.assertEqual(len(saved_objects), 2)
        notifications = list(DataNotification.objects.order_by("data_object_id"))
        self.assertEqual(len(notifications), 2)
        maximum_length = DataNotification._meta.get_field("message").max_length
        prefix = f"{self.owner.username} shared "
        suffix = " with you."
        title_budget = maximum_length - len(prefix) - len(suffix)
        expected_titles = (first_identifier, second_identifier)

        for notification, identifier in zip(notifications, expected_titles):
            with self.subTest(identifier_ending=identifier[-1]):
                self.assertLessEqual(len(notification.message), maximum_length)
                self.assertTrue(notification.message.startswith(prefix))
                self.assertTrue(notification.message.endswith(suffix))
                self.assertEqual(
                    notification.message[len(prefix):-len(suffix)],
                    identifier[:title_budget],
                )

    def test_identifier_recheck_reports_only_conflicts_and_saves_nothing(self):
        """
        The save service reports late conflicts before creating any batch row
        """
        JSONData.objects.create(
            owner=self.recipient,
            data={"identifier": "late-conflict"},
            size_bytes=1,
        )
        objects = [
            self._prepared("fresh-object"),
            self._prepared("late-conflict"),
        ]

        with self.assertRaises(UploadIdentifierConflict) as context:
            save_prepared_json_data(self.owner, objects)

        self.assertEqual(context.exception.identifiers, ("late-conflict",))
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertFalse(
            JSONData.objects.filter(data__identifier="fresh-object").exists()
        )


class UploadResourceViewTests(TestCase):
    """
    Test request level upload rejection and schema compatibility
    """

    def setUp(self):
        """
        Create and sign in the upload owner
        """
        self.owner = User.objects.create_user(
            username="upload-owner",
            password="password",
        )
        self.client.login(username="upload-owner", password="password")

    def _valid(self, identifier):
        """
        Build a minimal object satisfying every required top level field
        """
        return {
            "identifier": identifier,
            "title": "Title",
            "creator": "Creator",
            "creator_affiliation": "Affiliation",
            "date": "2026-08-09",
            "shared_with": [{"access_type": "c"}],
            "rights": "Rights",
            "rights_holder": "Rights holder",
            "software": "Software",
            "software_version": "1",
            "system": "System",
            "system_version": "1",
            "processor_specifications": "Processor",
            "input_path": "input",
            "results_path": "results",
            "RVE_size": "size",
            "RVE_continuity": True,
            "discretization_type": "type",
            "discretization_unit_size": "unit",
            "discretization_count": 1,
            "mechanical_BC": "boundary",
            "phase": "phase",
            "stress": "stress",
            "total_strain": "strain",
            "units": "units",
        }

    def _json_file(self, value, name="objects.json"):
        """
        Encode one value as a compact UTF8 uploaded JSON file
        """
        content = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return SimpleUploadedFile(
            name,
            content,
            content_type="application/json",
        )

    def _escaped_json_file(self, value, name="objects.json"):
        """
        Encode escaped JSON that may contain lone surrogate code points
        """
        content = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return SimpleUploadedFile(
            name,
            content,
            content_type="application/json",
        )

    def _messages(self, response):
        """
        Return the user facing messages attached to one response
        """
        return [
            str(message)
            for message in get_messages(response.wsgi_request)
        ]

    @override_settings(PILOT_MAX_UPLOAD_FILES=5)
    def test_file_count_rejection_saves_zero_objects(self):
        """
        A sixth file is rejected before any file can be persisted
        """
        files = []

        for index in range(6):
            files.append(
                self._json_file(
                    self._valid(f"object-{index}"),
                    f"object-{index}.json",
                )
            )

        response = self.client.post(
            reverse("upload_json"),
            {"file": files},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    @override_settings(PILOT_MAX_UPLOAD_FILE_BYTES=2048)
    def test_file_size_rejection_saves_zero_objects_from_the_request(self):
        """
        File prechecks prevent an earlier valid file from being persisted
        """
        valid_file = self._json_file(self._valid("first"), "first.json")
        oversized_file = SimpleUploadedFile(
            "oversized.json",
            b" " * 2049,
            content_type="application/json",
        )

        response = self.client.post(
            reverse("upload_json"),
            {"file": [valid_file, oversized_file]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertTrue(any("limit" in message.casefold() for message in self._messages(response)))

    @override_settings(
        PILOT_MAX_UPLOAD_FILE_BYTES=2048,
        PILOT_MAX_UPLOAD_REQUEST_BYTES=1000,
    )
    def test_combined_size_rejection_saves_zero_objects(self):
        """
        Combined byte rejection prevents individually valid files from saving
        """
        files = [
            self._json_file(self._valid("first"), "first.json"),
            self._json_file(self._valid("second"), "second.json"),
        ]

        self.assertLessEqual(files[0].size, 2048)
        self.assertLessEqual(files[1].size, 2048)
        self.assertGreater(files[0].size + files[1].size, 1000)

        response = self.client.post(
            reverse("upload_json"),
            {"file": files},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    @override_settings(PILOT_MAX_UPLOAD_OBJECTS=100)
    def test_object_limit_accepts_exactly_one_hundred_objects(self):
        """
        One hundred unwrapped objects remain inside the request limit
        """
        objects = []

        for index in range(100):
            objects.append(self._valid(f"object-{index}"))

        response = self.client.post(
            reverse("upload_json"),
            {"file": self._json_file(objects)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 100)

    @override_settings(PILOT_MAX_UPLOAD_OBJECTS=100)
    def test_object_limit_rejects_one_hundred_and_one_objects(self):
        """
        A one hundred and first object rejects the complete request
        """
        objects = []

        for index in range(101):
            objects.append(self._valid(f"object-{index}"))

        response = self.client.post(
            reverse("upload_json"),
            {"file": self._json_file(objects)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    @override_settings(PILOT_MAX_UPLOAD_OBJECTS=1)
    def test_object_limit_counts_schema_invalid_raw_objects(self):
        """
        Schema validation cannot hide raw objects from resource accounting
        """
        response = self.client.post(
            reverse("upload_json"),
            {
                "file": self._json_file(
                    [self._valid("valid"), {"identifier": "invalid"}]
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    @override_settings(PILOT_MAX_JSON_DEPTH=3)
    def test_depth_rejection_rolls_back_other_valid_files(self):
        """
        Excessive depth in a later file rejects every prepared object
        """
        nested_object = self._valid("too-deep")
        nested_object["extra"] = [[[0]]]

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": [
                    self._json_file(self._valid("first"), "first.json"),
                    self._json_file(nested_object, "deep.json"),
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    def test_nonfinite_number_rejects_the_complete_request(self):
        """
        A nonfinite number prevents every object in the batch from saving
        """
        invalid = self._valid("nonfinite")
        invalid["extra"] = float("nan")

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": self._json_file(
                    [self._valid("first"), invalid]
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    @patch("apps.pages.views.json.load", side_effect=AssertionError("parsed"))
    @patch("apps.pages.views.consume_rate_limit")
    def test_rate_limit_denial_happens_before_parsing(
        self,
        consume_mock,
        _load_mock,
    ):
        """
        A denied upload returns before any file content is parsed
        """
        consume_mock.return_value = RateLimitDecision(
            allowed=False,
            retry_after_seconds=37,
        )

        response = self.client.post(
            reverse("upload_json"),
            {"file": self._json_file(self._valid("denied"))},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "37")
        self.assertEqual(JSONData.objects.count(), 0)

    @override_settings(
        PILOT_RATE_LIMITS={
            "upload": {"limit": 1, "window_seconds": 3600},
        }
    )
    def test_upload_rate_limit_follows_user_across_client_addresses(self):
        """
        One user's upload bucket is shared across changing client addresses
        """
        first_response = self.client.post(
            reverse("upload_json"),
            {"file": self._json_file(self._valid("first"))},
            REMOTE_ADDR="192.0.2.10",
        )
        second_response = self.client.post(
            reverse("upload_json"),
            {"file": self._json_file(self._valid("second"))},
            REMOTE_ADDR="198.51.100.20",
        )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(JSONData.objects.count(), 1)

    def test_invalid_utf8_is_reported_without_saving(self):
        """
        Invalid UTF8 input is handled as an invalid file
        """
        uploaded_file = SimpleUploadedFile(
            "invalid-utf8.json",
            b"\xff",
            content_type="application/json",
        )

        response = self.client.post(
            reverse("upload_json"),
            {"file": uploaded_file},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 0)

    def test_invalid_json_is_reported_without_saving(self):
        """
        Invalid JSON input is handled without persisting an object
        """
        uploaded_file = SimpleUploadedFile(
            "invalid.json",
            b"{",
            content_type="application/json",
        )

        response = self.client.post(
            reverse("upload_json"),
            {"file": uploaded_file},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 0)

    def test_large_integer_parse_error_is_reported_without_saving(self):
        """
        A five thousand digit integer is handled as an invalid file
        """
        valid_prefix = json.dumps(
            self._valid("large-integer"),
            separators=(",", ":"),
        ).encode("utf-8")
        content = (
            valid_prefix[:-1]
            + b',"large_integer":'
            + (b"9" * 5000)
            + b"}"
        )
        uploaded_file = SimpleUploadedFile(
            "large-integer.json",
            content,
            content_type="application/json",
        )
        self.client.raise_request_exception = False

        response = self.client.post(
            reverse("upload_json"),
            {"file": uploaded_file},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 0)
        report = " ".join(self._messages(response))
        self.assertIn("large-integer.json", report)
        self.assertIn('data-upload-category="invalid_file"', report)
        self.assertIn("This file could not be read as JSON.", report)

    def test_lone_surrogate_value_rejects_the_complete_request(self):
        """
        A lone surrogate value leaves earlier prepared objects unsaved
        """
        invalid = self._valid("invalid-value")
        invalid["extra"] = "\ud800"
        self.client.raise_request_exception = False

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": self._escaped_json_file(
                    [self._valid("first"), invalid]
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertIn(
            "Uploaded JSON contains invalid Unicode text.",
            self._messages(response),
        )

    def test_lone_surrogate_key_rejects_the_complete_request(self):
        """
        A lone surrogate key leaves earlier prepared objects unsaved
        """
        invalid = self._valid("invalid-key")
        invalid["\ud800"] = "value"
        self.client.raise_request_exception = False

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": self._escaped_json_file(
                    [self._valid("first"), invalid]
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)
        self.assertIn(
            "Uploaded JSON contains invalid Unicode text.",
            self._messages(response),
        )

    @patch("apps.pages.views._identifier_exists", return_value=False)
    def test_transactional_identifier_recheck_rolls_back_the_file(
        self,
        _exists_mock,
    ):
        """
        A conflict missed during preparation prevents saving any object in the file
        """
        other_owner = User.objects.create_user(
            username="other-owner",
            password="password",
        )
        JSONData.objects.create(
            owner=other_owner,
            data={"identifier": "late-conflict"},
            size_bytes=1,
        )

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": self._json_file(
                    [
                        self._valid("fresh-object"),
                        self._valid("late-conflict"),
                    ]
                )
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertFalse(
            JSONData.objects.filter(data__identifier="fresh-object").exists()
        )
        messages = self._messages(response)
        self.assertTrue(any("Duplicate identifiers" in message for message in messages))
        self.assertTrue(any("late-conflict" in message for message in messages))

    @patch("apps.pages.views.json.load")
    def test_json_recursion_error_rejects_the_complete_request(self, load_mock):
        """
        Parser recursion failure rolls back objects prepared from earlier files
        """
        load_mock.side_effect = [self._valid("first"), RecursionError]

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": [
                    self._json_file(self._valid("first"), "first.json"),
                    self._json_file(self._valid("recursive"), "recursive.json"),
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 0)

    @override_settings(PILOT_MAX_USER_JSON_BYTES=50 * 1024 * 1024)
    def test_quota_rejection_saves_zero_new_objects(self):
        """
        Quota rejection leaves all objects from the file unpersisted
        """
        JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "existing"},
            size_bytes=50 * 1024 * 1024,
        )

        response = self.client.post(
            reverse("upload_json"),
            {
                "file": self._json_file(
                    [self._valid("first"), self._valid("second")]
                )
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertTrue(any("quota" in message.casefold() for message in self._messages(response)))
