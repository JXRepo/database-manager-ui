import copy
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.test.html import parse_html
from django.urls import reverse

from .models import DataNotification, JSONData
from .upload_services import canonical_json_size, data_fingerprint, generate_data_identifier


def _elements(element):
    """
    Traverse rendered report elements in file order

    Parameters
    ----------
    element : django.test.html.Element or str
        Parsed HTML node.

    Yields
    ------
    django.test.html.Element
        The node and each element descendant.
    """
    if isinstance(element, str):
        return
    yield element
    for child in element.children:
        yield from _elements(child)


class UploadFileAtomicityTests(TestCase):
    """
    Require every object in one JSON file to pass before saving any of them
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create isolated upload users and complete required metadata
        """
        cls.owner = User.objects.create_user(username="file-atomicity-owner")
        cls.recipient = User.objects.create_user(username="file-atomicity-recipient")
        cls.example = {
            "title": "Title", "creator": "Creator", "creator_affiliation": "Affiliation",
            "date": "2026-09-18", "shared_with": [{"access_type": "c"}],
            "rights": "Rights", "rights_holder": "Rights holder", "software": "Software",
            "software_version": "1", "system": "System", "system_version": "1",
            "processor_specifications": "Processor", "input_path": "input", "results_path": "results",
            "RVE_size": "size", "RVE_continuity": True, "discretization_type": "type",
            "discretization_unit_size": "unit", "discretization_count": 1,
            "mechanical_BC": "boundary", "phase": "phase", "stress": "stress",
            "total_strain": "strain", "units": "units",
        }

    def setUp(self):
        """
        Sign in as the owner of the uploaded files
        """
        self.client.force_login(self.owner)

    def _data(self, title, identifier=None):
        """
        Build a fresh valid object without depending on local example files

        Parameters
        ----------
        title : str
            Distinct object title.
        identifier : str, optional
            Supplied identifier, omitted when None.

        Returns
        -------
        dict
            Complete upload object.
        """
        data = copy.deepcopy(self.example)
        data["title"] = title
        if identifier is not None:
            data["identifier"] = identifier
        return data

    def _upload(self, payload):
        """
        Submit one JSON file through the real upload endpoint

        Parameters
        ----------
        payload : object
            File content to encode as JSON.

        Returns
        -------
        HttpResponse
            Upload feedback reached after following the redirect.
        """
        return self._upload_files(payload)

    def _upload_files(self, *payloads):
        """
        Submit JSON files in a controlled order through the upload endpoint

        Parameters
        ----------
        payloads : object
            One JSON payload per file in submission order.

        Returns
        -------
        HttpResponse
            Upload feedback after following any redirect.
        """
        uploaded = []
        for index, payload in enumerate(payloads, start=1):
            uploaded.append(SimpleUploadedFile(
                f"file-{index}.json", json.dumps(payload).encode("utf-8"), content_type="application/json",
            ))
        response = self.client.post(reverse("upload_json"), {"file": uploaded}, follow=True)
        self.assertEqual(response.status_code, 200)
        return response

    def _assert_file_statuses(self, response, expected):
        """
        Check ordered file outcomes without assigning errors to unprocessed objects

        Parameters
        ----------
        response : HttpResponse
            Upload feedback containing a failed file.
        expected : list of str
            Expected uploaded, failed, or skipped state for each file.
        """
        files = [node for node in _elements(parse_html(response.content.decode()))
                 if "data-upload-file" in dict(node.attributes)]
        self.assertEqual([dict(node.attributes).get("data-upload-file-status") for node in files], expected)
        for file, status in zip(files, expected):
            if status in {"uploaded", "skipped"}:
                self.assertFalse(any("data-upload-object" in dict(node.attributes) for node in _elements(file)))

    def test_any_invalid_object_prevents_saving_valid_neighbors(self):
        """
        Reject the complete file for schema, identifier, structure, or sharing errors
        """
        for error in ("missing", "empty", "object_type", "identifier_type", "sharing"):
            with self.subTest(error=error):
                first = self._data(f"First valid {error}", f"first-{error}")
                last = self._data(f"Last valid {error}", f"last-{error}")
                invalid = self._data(f"Invalid {error}", f"invalid-{error}")
                if error == "missing":
                    invalid.pop("phase")
                elif error == "empty":
                    invalid["software"] = ""
                elif error == "object_type":
                    invalid = False
                elif error == "identifier_type":
                    invalid["identifier"] = 42
                else:
                    invalid["shared_with"] = [{"access_type": "c", "username": "missing-recipient"}]
                before = JSONData.objects.count()

                response = self._upload([first, invalid, last])

                self.assertEqual(JSONData.objects.count(), before)
                self.assertFalse(JSONData.objects.filter(data__identifier=first["identifier"]).exists())
                self.assertFalse(JSONData.objects.filter(data__identifier=last["identifier"]).exists())
                self.assertContains(response, "data-upload-report")

    def test_repeated_identifiers_or_generated_content_reject_the_complete_file(self):
        """
        Discard valid neighbors as well as both occurrences of a duplicate
        """
        for supplied in (True, False):
            with self.subTest(supplied=supplied):
                neighbor = self._data(f"Distinct neighbor {supplied}", f"neighbor-{supplied}")
                repeated = self._data(f"Repeated object {supplied}", "repeated-id" if supplied else None)
                before = JSONData.objects.count()

                response = self._upload([neighbor, repeated, copy.deepcopy(repeated)])

                self.assertEqual(JSONData.objects.count(), before)
                self.assertContains(response, 'data-upload-category="duplicate_identifier"')

    def test_existing_identifier_rejects_the_file_without_changing_stored_data(self):
        """
        Leave existing private data untouched when one uploaded object conflicts
        """
        original = self._data("Existing private original", "existing-id")
        stored = JSONData.objects.create(owner=self.recipient, access_type="c", data=original)
        neighbor = self._data("Valid candidate", "neighbor-id")

        response = self._upload([neighbor, self._data("Conflicting upload", "existing-id")])

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertFalse(JSONData.objects.filter(owner=self.owner).exists())
        stored.refresh_from_db()
        self.assertEqual(stored.data, original)
        self.assertEqual(stored.owner, self.recipient)
        self.assertContains(response, 'data-upload-category="duplicate_identifier"')

    def test_all_valid_objects_in_a_wrapped_file_are_saved_together(self):
        """
        Preserve normal complete uploads and automatic identifier allocation
        """
        first = self._data("Generated identifier object")
        second = self._data("Supplied identifier object", "supplied-id")

        response = self._upload({"data": [first, second]})

        self.assertEqual(JSONData.objects.count(), 2)
        self.assertEqual(JSONData.objects.get(data__identifier="supplied-id").data, second)
        generated = JSONData.objects.get(data__title=first["title"])
        self.assertRegex(generated.data["identifier"], r"^[0-9a-z]{8}$")
        self.assertEqual(generated.data, dict(first, identifier=generated.data["identifier"]))
        self.assertNotContains(response, "data-upload-report")

    def test_failed_file_does_not_reserve_identifiers_before_a_corrected_retry(self):
        """
        Save every corrected object once without conflicts from the rejected attempt
        """
        first = self._data("Generated candidate before error")
        expected_identifier = generate_data_identifier(first)
        invalid = self._data("Repair this object", "repaired-id")
        invalid.pop("phase")

        self._upload([first, invalid])

        self.assertEqual(JSONData.objects.count(), 0)
        invalid["phase"] = "phase"
        response = self._upload([first, invalid])
        self.assertEqual(JSONData.objects.count(), 2)
        self.assertEqual(JSONData.objects.get(data__title=first["title"]).data["identifier"], expected_identifier)
        self.assertEqual(JSONData.objects.get(data__identifier="repaired-id").data, invalid)
        self.assertNotContains(response, "data-upload-report")

    def test_rejected_file_creates_no_sharing_notifications(self):
        """
        Avoid notifying recipients about objects from a file that was not saved
        """
        shared = self._data("Shared candidate", "shared-candidate")
        shared["shared_with"] = [{"access_type": "c", "username": self.recipient.username}]
        invalid = self._data("Invalid neighbor", "invalid-neighbor")
        invalid["rights"] = None

        self._upload([shared, invalid])

        self.assertFalse(DataNotification.objects.exists())
        self.assertFalse(JSONData.objects.exists())

    def test_processing_stops_at_failed_file_and_preserves_earlier_uploads_and_notifications(self):
        """
        Keep a successful file while rejecting the next file and skipping later files
        """
        first = self._data("Successful first file", "first-file")
        first["shared_with"] = [{"access_type": "c", "username": self.recipient.username}]
        candidate = self._data("Candidate in rejected file", "rejected-candidate")
        invalid = self._data("Invalid object in second file", "invalid-second")
        invalid.pop("phase")
        later = self._data("Unprocessed later file", "later-file")

        response = self._upload_files(first, [candidate, invalid], later)

        self.assertEqual(JSONData.objects.count(), 1)
        stored = JSONData.objects.get()
        self.assertEqual(stored.data, first)
        notification = DataNotification.objects.get()
        self.assertEqual(notification.data_object_id, stored.pk)
        self.assertEqual(notification.recipient, self.recipient)
        self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])

    def test_duplicate_from_an_earlier_file_rejects_the_whole_current_file(self):
        """
        Preserve the earlier identifier and discard all objects in the conflicting file
        """
        first = self._data("First occurrence", "cross-file-id")
        second = [self._data("Valid neighbor of duplicate", "discarded-neighbor"),
                  self._data("Later conflicting occurrence", "cross-file-id")]

        response = self._upload_files(first, second, self._data("Skipped after duplicate", "skipped-duplicate"))

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, first)
        self.assertContains(response, 'data-upload-category="duplicate_identifier"')
        self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])

    def test_generated_and_legacy_digest_duplicates_are_rejected_across_files_in_both_orders(self):
        """
        Keep generated content and its legacy full digest in the same batch namespace
        """
        for generated_first in (True, False):
            with self.subTest(generated_first=generated_first):
                generated = self._data(f"Generated and legacy content {generated_first}")
                fingerprint = data_fingerprint(generated)
                legacy = dict(generated, identifier=fingerprint)
                first, second = (generated, legacy) if generated_first else (legacy, generated)
                later = self._data(f"Skipped after legacy duplicate {generated_first}", f"legacy-skipped-{generated_first}")
                before = JSONData.objects.count()

                response = self._upload_files(first, second, later)

                self.assertEqual(JSONData.objects.count(), before + 1)
                stored = JSONData.objects.get(data__title=generated["title"])
                if generated_first:
                    self.assertRegex(stored.data["identifier"], r"^[0-9a-z]{8}$")
                    self.assertEqual(stored.identifier_fingerprint, fingerprint)
                else:
                    self.assertEqual(stored.data, legacy)
                self.assertFalse(JSONData.objects.filter(data__identifier=later["identifier"]).exists())
                self.assertContains(response, 'data-upload-category="duplicate_identifier"')
                self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])

    def test_transactional_identifier_conflict_rolls_back_only_the_current_file(self):
        """
        Retain earlier commits when the final locked recheck rejects a later file
        """
        original = self._data("Existing private blocker", "recheck-blocker")
        blocker = JSONData.objects.create(owner=self.recipient, access_type="c", data=original)
        first = self._data("Committed before recheck failure", "before-recheck")
        second = [self._data("Candidate before late conflict", "late-candidate"),
                  self._data("Conflict caught during save", "recheck-blocker")]
        with patch("apps.pages.views._identifier_exists", return_value=False):
            response = self._upload_files(first, second, self._data("Skipped after conflict", "after-recheck"))

        self.assertEqual(JSONData.objects.count(), 2)
        self.assertEqual(JSONData.objects.get(owner=self.owner).data, first)
        blocker.refresh_from_db()
        self.assertEqual(blocker.data, original)
        self.assertContains(response, 'data-upload-category="duplicate_identifier"')
        self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])

    def test_empty_lists_fail_without_reporting_a_successful_upload(self):
        """
        Reject empty direct and wrapped lists before processing the following file
        """
        for payload in ([], {"data": []}):
            with self.subTest(payload=payload):
                response = self._upload_files(payload, self._data("Skipped after empty file", "after-empty"))

                self.assertFalse(JSONData.objects.exists())
                self.assertContains(response, 'data-upload-category="empty_file"')
                self.assertNotContains(response, "Upload successful")
                self._assert_file_statuses(response, ["failed", "skipped"])

    def test_notification_failure_rolls_back_only_current_file_objects_and_notifications(self):
        """
        Keep earlier notifications when notification persistence aborts a later file
        """
        failing_recipient = User.objects.create_user(username="notification-failure-recipient")
        first = self._data("Committed notification", "notification-first")
        first["shared_with"] = [{"access_type": "c", "username": self.recipient.username}]
        second_first = self._data("Notification rolled back with later object", "notification-second-first")
        second_first["shared_with"] = [{"access_type": "c", "username": self.recipient.username}]
        second_last = self._data("Notification persistence fails", "notification-second-last")
        second_last["shared_with"] = [{"access_type": "c", "username": failing_recipient.username}]
        create_notification = DataNotification.objects.create

        def create_with_failure(*args, **kwargs):
            """
            Fail only the chosen recipient while retaining real writes for earlier objects

            Parameters
            ----------
            args : tuple
                Positional arguments forwarded to the real model manager.
            kwargs : dict
                Notification fields including the recipient.

            Returns
            -------
            DataNotification
                Persisted notification for other recipients.

            Raises
            ------
            IntegrityError
                When the final object in the second file creates its notification.
            """
            if kwargs["recipient"].pk == failing_recipient.pk:
                raise IntegrityError("Simulated notification persistence failure")
            return create_notification(*args, **kwargs)

        with patch("apps.pages.upload_services.DataNotification.objects.create", side_effect=create_with_failure) as mocked:
            response = self._upload_files(
                first, [second_first, second_last], self._data("Skipped after database failure", "notification-third"),
            )

        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(JSONData.objects.count(), 1)
        stored = JSONData.objects.get()
        self.assertEqual(stored.data, first)
        notification = DataNotification.objects.get()
        self.assertEqual(notification.data_object_id, stored.pk)
        self.assertEqual(notification.recipient, self.recipient)
        self.assertContains(response, 'data-upload-category="save_error"')
        self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])

    def test_storage_quota_rejects_the_current_whole_file_but_keeps_the_previous_file(self):
        """
        Apply quota to a complete file even when its first object alone would fit
        """
        first = self._data("First file fits", "quota-first")
        candidate = self._data("First object could fit", "quota-candidate")
        overflow = self._data("Second object exceeds remaining quota", "quota-overflow")
        quota = canonical_json_size(first) + canonical_json_size(candidate)
        with override_settings(PILOT_MAX_USER_JSON_BYTES=quota):
            response = self._upload_files(first, [candidate, overflow], self._data("Skipped after quota", "quota-later"))

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, first)
        self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])

    def test_corrected_later_file_can_reuse_its_discarded_identifiers(self):
        """
        Let a rejected later file be retried without duplicate records or reserved IDs
        """
        first = self._data("Earlier successful file", "retry-first")
        candidate = self._data("Generated candidate in later file")
        expected_identifier = generate_data_identifier(candidate)
        invalid = self._data("Repair later file", "retry-later")
        invalid.pop("software")
        later = self._data("Unprocessed third file", "retry-skipped")

        response = self._upload_files(first, [candidate, invalid], later)

        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, first)
        self._assert_file_statuses(response, ["uploaded", "failed", "skipped"])
        invalid["software"] = "Software"
        corrected = self._upload([candidate, invalid])
        self.assertEqual(JSONData.objects.count(), 3)
        self.assertEqual(JSONData.objects.get(data__title=candidate["title"]).data["identifier"], expected_identifier)
        self.assertEqual(JSONData.objects.get(data__identifier="retry-later").data, invalid)
        self.assertFalse(JSONData.objects.filter(data__identifier="retry-skipped").exists())
        self.assertNotContains(corrected, "data-upload-report")

    def test_generated_files_with_colliding_previews_extend_identifiers_during_save(self):
        """
        Allow distinct generated content to extend a shared preview prefix at commit
        """
        first = self._data("First generated content with a shared prefix")
        second = self._data("Second generated content with a shared prefix")
        first_fingerprint = data_fingerprint(first)
        second_fingerprint = data_fingerprint(second)
        self.assertNotEqual(first_fingerprint, second_fingerprint)
        with patch("apps.pages.upload_services._identifier_candidates", return_value=["abcd1234", "abcd1234a"]):
            response = self._upload_files(first, second)

        self.assertEqual(JSONData.objects.count(), 2)
        for payload, identifier, fingerprint in [
            (first, "abcd1234", first_fingerprint),
            (second, "abcd1234a", second_fingerprint),
        ]:
            stored = JSONData.objects.get(data__title=payload["title"])
            final_data = dict(payload, identifier=identifier)
            self.assertEqual(stored.data, final_data)
            self.assertEqual(stored.identifier_fingerprint, fingerprint)
            self.assertEqual(stored.size_bytes, canonical_json_size(final_data))
        self.assertNotContains(response, "data-upload-report")
