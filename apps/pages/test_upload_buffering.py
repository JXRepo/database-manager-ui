import json
import os
import tracemalloc
import weakref
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS
from .models import JSONData
from .upload_services import validate_json_depth


class TrackedDataObject(dict):
    """
    Allow tests to observe when parsed upload data leaves memory
    """


class UploadBufferingTests(TestCase):
    """
    Keep upload memory bounded by the current file and JSON nesting depth
    """

    @override_settings(FILE_UPLOAD_HANDLERS=["django.core.files.uploadhandler.TemporaryFileUploadHandler"])
    def test_preflight_releases_parsed_files_and_processing_releases_completed_files(self):
        """
        Release parsed trees while keeping temporary uploads readable until completion
        """
        owner = User.objects.create_user(username="buffering-owner")
        self.client.force_login(owner)
        files = []
        for index in range(3):
            data = dict.fromkeys(REQUIRED_TOP_LEVEL_FIELDS, "metadata")
            data.update(identifier=f"buffering-{index}", shared_with=[{"access_type": "c"}])
            files.append(SimpleUploadedFile(f"{index}.json", json.dumps(data).encode("utf-8")))
        references = []
        original_load = json.load

        def track_load(uploaded_file):
            """
            Track the lifetime of a parsed file without retaining its data

            Parameters
            ----------
            uploaded_file : UploadedFile
                File passed to the JSON parser.

            Returns
            -------
            TrackedDataObject
                Ordinary JSON mapping with weak reference support.
            """
            data = TrackedDataObject(original_load(uploaded_file))
            references.append(weakref.ref(data))
            return data

        with patch("apps.pages.views.json.load", side_effect=track_load):
            response = self.client.post(
                reverse("upload_json"), {"file": files}, HTTP_ACCEPT="application/x-ndjson",
            )
            self.addCleanup(response.close)
            self.assertTrue(response.streaming)
            paths = [file.temporary_file_path() for file in response.wsgi_request.FILES.getlist("file")]
            self.assertTrue(all(os.path.exists(path) for path in paths))
            self.assertEqual(len(references), 3)
            self.assertTrue(all(reference() is None for reference in references))
            self.assertFalse(JSONData.objects.exists())

            for chunk in response.streaming_content:
                event = json.loads(chunk)
                if event["type"] == "file_result":
                    self.assertEqual(event["status"], "uploaded")
                    self.assertTrue(all(reference() is None for reference in references))

        self.assertEqual(len(references), 6)
        self.assertEqual(JSONData.objects.count(), 3)
        response.close()
        self.assertFalse(any(os.path.exists(path) for path in paths))

    def test_depth_validation_does_not_allocate_work_for_every_array_value(self):
        """
        Inspect a wide numeric array without creating a second array of work items
        """
        values = [0] * 100000
        tracemalloc.start()
        try:
            validate_json_depth(values)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak_bytes, 1024 * 1024)
