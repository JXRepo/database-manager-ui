import copy
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from .upload_test_data import valid_upload_object
from .models import DataNotification, JSONData, RateLimitBucket


class UploadProgressTests(TestCase):
    """
    Keep streamed file progress aligned with validation and committed data
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create isolated users and complete required metadata
        """
        cls.owner = User.objects.create_user(username="progress-owner")
        cls.recipient = User.objects.create_user(username="progress-recipient")
        cls.example = valid_upload_object()

    def setUp(self):
        """
        Authenticate the owner for normal upload requests
        """
        self.client.force_login(self.owner)

    def _data(self, title, identifier=None):
        """
        Build independent valid metadata for one data object

        Parameters
        ----------
        title : str
            Distinct title for this object.
        identifier : str, optional
            Supplied identifier, omitted when None.

        Returns
        -------
        dict
            Complete data object.
        """
        data = copy.deepcopy(self.example)
        data["title"] = title
        if identifier is not None:
            data["identifier"] = identifier
        return data

    def _file(self, payload, name="data.json"):
        """
        Encode a JSON payload or preserve deliberately invalid file bytes

        Parameters
        ----------
        payload : object
            JSON content, or raw bytes for unreadable file cases.
        name : str, optional
            Original upload filename.

        Returns
        -------
        SimpleUploadedFile
            Fresh multipart upload input.
        """
        content = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return SimpleUploadedFile(name, content, content_type="application/json")

    def _post(self, *payloads):
        """
        Request live progress for files with deliberately identical names

        Parameters
        ----------
        payloads : object
            Ordered JSON payloads or raw file bytes.

        Returns
        -------
        HttpResponse
            Streaming progress or a rejected request.
        """
        return self.client.post(
            reverse("upload_json"), {"file": [self._file(payload) for payload in payloads]},
            HTTP_ACCEPT="application/x-ndjson", HTTP_X_UPLOAD_PROGRESS="objects",
        )

    def _events(self, response, include_progress=False):
        """
        Consume application events while checking the streaming contract

        Parameters
        ----------
        response : HttpResponse
            Upload response to consume.
        include_progress : bool, optional
            Include intermediate object counts as well as file results.

        Yields
        ------
        dict
            One newline delimited JSON event.
        """
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.assertEqual(response.headers["Content-Type"].split(";")[0], "application/x-ndjson")
        self.addCleanup(response.close)
        for chunk in response.streaming_content:
            for line in chunk.splitlines():
                if line.strip():
                    event = json.loads(line)
                    if include_progress or event["type"] != "file_progress":
                        yield event

    def test_stream_checks_every_object_and_reports_counts_before_saving(self):
        """
        Expose real object checks even when thirty errors reject all hundred objects
        """
        records = [self._data(f"Object {index}", f"object-{index}") for index in range(100)]
        for record in records[:30]:
            record.pop("phase")
        observed = []
        for event in self._events(self._post(records), include_progress=True):
            if event["type"] == "file_progress":
                observed.append((event["stage"], event["completed"], event["total"]))
                self.assertFalse(JSONData.objects.exists())
        self.assertTrue(observed, "The stream must report object progress before its final result")
        self.assertEqual(observed[0], ("parsing", 0, None))
        self.assertEqual(observed[1:], [("validating", index, 100) for index in range(101)])
        self.assertFalse(JSONData.objects.exists())
        self.assertEqual(event["level"], "error")

    def test_stream_reports_provisional_saves_before_the_confirmed_result(self):
        """
        Count each actual save without declaring success until the file commits
        """
        records = [self._data(f"Object {index}", f"object-{index}") for index in range(3)]
        observed = []
        for event in self._events(self._post(records), include_progress=True):
            if event["type"] == "file_progress":
                observed.append((event["stage"], event["completed"], event["total"]))
                if event["stage"] == "validating":
                    self.assertFalse(JSONData.objects.exists())
                elif event["stage"] == "saving":
                    self.assertEqual(JSONData.objects.count(), event["completed"])
            elif event["type"] == "file_result":
                self.assertEqual(event["status"], "uploaded")
                self.assertEqual(event["saved_count"], 3)
                self.assertTrue(observed, "The stream must report provisional saves before success")
                self.assertEqual(observed[-1], ("saving", 3, 3))
        self.assertEqual(observed, [("parsing", 0, None)] +
                         [("validating", index, 3) for index in range(4)] +
                         [("saving", index, 3) for index in range(4)])

    def test_disconnected_stream_rolls_back_the_current_file_and_notifications(self):
        """
        Keep earlier commits and discard a file interrupted during provisional saving
        """
        shared = self._data("Shared", "shared")
        shared["shared_with"] = [{"access_type": "c", "username": self.recipient.username}]
        response = self._post(self._data("Confirmed", "confirmed"), [shared, self._data("Later", "later")])
        events = self._events(response, include_progress=True)
        for event in events:
            if (event["type"] == "file_progress" and event["index"] == 1
                    and event["stage"] == "saving" and event["completed"] == 1):
                self.assertEqual(JSONData.objects.count(), 2)
                self.assertEqual(DataNotification.objects.count(), 1)
                response.close()
                break
        else:
            self.fail("The stream never exposed a provisional object save")
        self.assertEqual(list(JSONData.objects.values_list("data__identifier", flat=True)), ["confirmed"])
        self.assertFalse(DataNotification.objects.exists())

    def test_each_file_starts_before_its_writes_and_finishes_before_the_next(self):
        """
        Emit real sequential progress instead of saving everything before streaming
        """
        response = self._post(self._data("First", "first"), self._data("Second", "second"))
        events = self._events(response)

        self.assertEqual(next(events), {"type": "file_start", "index": 0})
        self.assertFalse(JSONData.objects.exists())
        self.assertEqual(next(events), {
            "type": "file_result", "index": 0, "status": "uploaded", "saved_count": 1,
        })
        self.assertEqual(list(JSONData.objects.values_list("data__identifier", flat=True)), ["first"])
        self.assertEqual(next(events), {"type": "file_start", "index": 1})
        self.assertFalse(JSONData.objects.filter(data__identifier="second").exists())
        self.assertEqual(next(events), {
            "type": "file_result", "index": 1, "status": "uploaded", "saved_count": 1,
        })
        self.assertEqual(JSONData.objects.count(), 2)
        complete = next(events)
        self.assertEqual(complete["type"], "complete")
        self.assertEqual(complete["level"], "success")
        self.assertIn("2 data object(s)", complete["summary"])
        self.assertIn("2 file(s)", complete["summary"])
        self.assertEqual(complete["report_html"], "")
        with self.assertRaises(StopIteration):
            next(events)

    def test_same_named_files_keep_order_through_syntax_and_empty_file_errors(self):
        """
        Give every original file a result and continue after unreadable content
        """
        events = list(self._events(self._post(
            self._data("First", "first"), b"{", self._data("Third", "third"),
            b"", self._data("Fifth", "fifth"),
        )))

        self.assertEqual(
            [(event["type"], event.get("index")) for event in events],
            [("file_start", 0), ("file_result", 0), ("file_start", 1), ("file_result", 1),
             ("file_start", 2), ("file_result", 2), ("file_start", 3), ("file_result", 3),
             ("file_start", 4), ("file_result", 4), ("complete", None)],
        )
        results = [event for event in events if event["type"] == "file_result"]
        self.assertEqual([event["status"] for event in results],
                         ["uploaded", "failed", "uploaded", "failed", "uploaded"])
        self.assertEqual([event["saved_count"] for event in results], [1, 0, 1, 0, 1])
        self.assertEqual(JSONData.objects.count(), 3)
        self.assertEqual(events[-1]["level"], "warning")
        self.assertIn("3 file(s) uploaded", events[-1]["summary"])
        self.assertIn("2 file(s) failed", events[-1]["summary"])
        self.assertEqual(events[-1]["report_html"].count('data-upload-file-status="failed"'), 2)

    def test_rejected_file_reports_all_objects_and_escapes_uploaded_text(self):
        """
        Preserve complete atomic validation and safe report HTML in the stream
        """
        malicious_title = '<img src=x onerror="alert(1)">'
        invalid = self._data(malicious_title, "invalid-first")
        invalid.pop("phase")
        invalid["creator"] = ""
        invalid["shared_with"] = [{"access_type": "c", "username": "unknown-progress-user"}]
        later_invalid = self._data("Second invalid object", " spaced ")
        later_invalid["software"] = ""
        shared = self._data("Valid neighbor", "valid-neighbor")
        shared["shared_with"] = [{"access_type": "c", "username": self.recipient.username}]

        events = list(self._events(self._post(
            [invalid, later_invalid, shared], self._data("Later valid file", "later-valid"),
        )))

        self.assertEqual(events[1]["status"], "failed")
        self.assertEqual(events[3]["status"], "uploaded")
        self.assertEqual(list(JSONData.objects.values_list("data__identifier", flat=True)), ["later-valid"])
        self.assertFalse(DataNotification.objects.exists())
        report = events[-1]["report_html"]
        for category in ("missing_required", "empty_values", "invalid_identifier", "unknown_share_user"):
            self.assertIn(f'data-upload-category="{category}"', report)
        self.assertIn(str(escape(malicious_title)), report)
        self.assertNotIn(malicious_title, report)
        self.assertLess(report.index(str(escape(malicious_title))), report.index("Second invalid object"))

    def test_global_limits_reject_the_batch_before_any_saves(self):
        """
        Keep file count, request bytes, and raw object count as request limits
        """
        invalid = self._data("Invalid object still counts")
        invalid.pop("phase")
        cases = [
            ({"PILOT_MAX_UPLOAD_FILES": 1}, [self._data("First"), self._data("Second")]),
            ({"PILOT_MAX_UPLOAD_REQUEST_BYTES": 100}, [self._data("First")]),
            ({"PILOT_MAX_UPLOAD_OBJECTS": 2}, [self._data("First"), [invalid, self._data("Third")]]),
        ]
        for limits, payloads in cases:
            with self.subTest(limits=limits), override_settings(**limits):
                response = self._post(*payloads)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.streaming)
                self.assertIsInstance(response.json()["error"], str)
                self.assertTrue(response.json()["error"])
                self.assertFalse(JSONData.objects.exists())
                self.assertFalse(DataNotification.objects.exists())

    def test_missing_file_returns_a_readable_request_error(self):
        """
        Return a JSON error rather than an HTML form to the progress client
        """
        response = self._post()

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["error"])
        self.assertFalse(JSONData.objects.exists())

    def test_generated_duplicates_fail_only_the_repeated_file(self):
        """
        Keep identifier deduplication when each save occurs inside the iterator
        """
        repeated = self._data("Repeated generated object")
        events = list(self._events(self._post(repeated, repeated, self._data("Distinct generated object"))))

        self.assertEqual([event["status"] for event in events if event["type"] == "file_result"],
                         ["uploaded", "failed", "uploaded"])
        self.assertEqual(JSONData.objects.count(), 2)
        self.assertIn('data-upload-category="duplicate_identifier"', events[-1]["report_html"])
        for identifier in JSONData.objects.values_list("data__identifier", flat=True):
            self.assertRegex(identifier, r"^[a-z0-9]{8}$")

    @override_settings(PILOT_MAX_USER_JSON_BYTES=2000)
    def test_quota_failure_keeps_confirmed_results_and_allows_a_later_smaller_file(self):
        """
        Report quota rejection without discarding earlier files or blocking later ones
        """
        large = self._data("Too large", "large")
        large["extra"] = "x" * 5000
        events = list(self._events(self._post(
            self._data("First", "first"), large, self._data("Last", "last"),
        )))

        self.assertEqual([event["status"] for event in events if event["type"] == "file_result"],
                         ["uploaded", "failed", "uploaded"])
        self.assertEqual(set(JSONData.objects.values_list("data__identifier", flat=True)), {"first", "last"})
        self.assertIn('data-upload-category="storage_limit"', events[-1]["report_html"])

    @override_settings(PILOT_RATE_LIMITS={"upload": {"limit": 1, "window_seconds": 3600}})
    def test_five_files_consume_one_attempt_and_a_second_batch_is_rate_limited(self):
        """
        Keep rate accounting per request instead of consuming an attempt per file
        """
        events = list(self._events(self._post(*(self._data(f"File {index}") for index in range(5)))))

        self.assertEqual(events[-1]["level"], "success")
        self.assertEqual(JSONData.objects.count(), 5)
        self.assertEqual(RateLimitBucket.objects.get(scope="upload").count, 1)
        response = self._post(self._data("Blocked"))
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)
        self.assertFalse(JSONData.objects.filter(data__title="Blocked").exists())

    def test_stream_feedback_does_not_reappear_on_the_next_page_visit(self):
        """
        Keep streamed feedback out of message cookies and later page responses
        """
        invalid = self._data("Invalid")
        invalid.pop("phase")
        events = list(self._events(self._post(invalid)))

        self.assertEqual(events[-1]["level"], "error")
        self.assertIn('data-upload-report', events[-1]["report_html"])
        response = self.client.get(reverse("upload_json"))
        self.assertNotContains(response, "data-upload-report")
        self.assertNotContains(response, "Upload finished:")

    def test_live_progress_requires_login(self):
        """
        Preserve the authenticated upload boundary for the progress media type
        """
        self.client.logout()
        response = self._post(self._data("Unauthenticated"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.headers["Location"])
        self.assertFalse(JSONData.objects.exists())

    def test_existing_clients_keep_the_original_file_event_protocol(self):
        """
        Let an already open upload page finish after the server gains object progress
        """
        response = self.client.post(
            reverse("upload_json"), {"file": self._file(self._data("Existing page", "existing-page"))},
            HTTP_ACCEPT="application/x-ndjson",
        )
        events = list(self._events(response, include_progress=True))
        self.assertEqual([event["type"] for event in events], ["file_start", "file_result", "complete"])
        self.assertEqual(events[1]["status"], "uploaded")
        self.assertEqual(JSONData.objects.count(), 1)

    def test_live_progress_requires_csrf_protection(self):
        """
        Reject a progress upload without the signed in user's CSRF token
        """
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post(
            reverse("upload_json"), {"file": self._file(self._data("Missing token"))},
            HTTP_ACCEPT="application/x-ndjson",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(JSONData.objects.exists())

    def test_native_upload_still_redirects_to_the_result_page(self):
        """
        Keep the normal form submission usable without streaming JavaScript
        """
        response = self.client.post(
            reverse("upload_json"), {"file": self._file(self._data("Native upload", "native"))},
        )

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(response.streaming)
        self.assertTrue(JSONData.objects.filter(data__identifier="native").exists())
