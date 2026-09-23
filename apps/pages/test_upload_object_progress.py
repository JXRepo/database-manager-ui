import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection
from django.test import TestCase

from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS
from .models import JSONData
from .views import _process_upload_file


class UploadObjectProgressTests(TestCase):
    """
    Verify object counts and task results match real atomic saves
    """

    def setUp(self):
        """
        Prepare isolated metadata and its original file report
        """
        self.owner = User.objects.create_user(username="object-progress-owner")
        self.objects = []
        for index in range(3):
            data = dict.fromkeys(REQUIRED_TOP_LEVEL_FIELDS, "metadata")
            data.update(identifier=f"progress-{index}", shared_with=[{"access_type": "c"}])
            self.objects.append(data)
        self.report = {
            "name": "objects.json", "issues": {}, "objects": [],
            "status": "failed", "saved_count": 0,
        }

    def process(self, **callbacks):
        """
        Process an actual JSON file using optional observers

        Parameters
        ----------
        **callbacks : callable
            Progress and commit observers used by a background worker.
        """
        uploaded = SimpleUploadedFile("objects.json", json.dumps(self.objects).encode())
        _process_upload_file(self.owner, self.report, uploaded, 1, set(), **callbacks)

    def test_progress_counts_validated_objects_before_any_commit(self):
        """
        Publish completed validation counts without claiming premature saves
        """
        observations = []

        def observe(stage, completed, total):
            """
            Capture progress together with the actual saved record count

            Parameters
            ----------
            stage : str
                Current processing stage.
            completed : int
                Number of completed object checks.
            total : int or None
                Number of objects once parsing has completed.
            """
            observations.append((stage, completed, total, JSONData.objects.count()))

        self.process(progress=observe)
        validations = [item for item in observations if item[0] == "validating"]
        self.assertEqual([item[1] for item in validations], [0, 1, 2, 3])
        self.assertTrue(all(item[2:] == (3, 0) for item in validations))
        self.assertEqual(observations[-1], ("saving", 3, 3, 0))
        self.assertEqual(self.report["saved_count"], 3)

    def test_invalid_objects_are_counted_and_do_not_trigger_save_callback(self):
        """
        Finish all independent checks while rejecting the entire invalid file
        """
        self.objects[0] = 12
        self.objects[1].pop("phase")
        observations = []
        self.process(progress=lambda *event: observations.append(event))
        self.assertEqual(observations[-1], ("validating", 3, 3))
        self.assertFalse(JSONData.objects.exists())
        self.assertEqual(self.report["status"], "failed")
        self.assertTrue(self.report["objects"][0]["issues"])
        self.assertTrue(self.report["objects"][1]["issues"])

    def test_task_result_failure_rolls_back_objects(self):
        """
        Roll back saved data when the matching task result cannot be recorded
        """
        def fail_result(report):
            """
            Simulate failure to persist the otherwise successful task result

            Parameters
            ----------
            report : dict
                Confirmed file result still inside its save transaction.
            """
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(report["status"], "uploaded")
            self.assertEqual(report["saved_count"], 3)
            self.assertEqual(JSONData.objects.count(), 3)
            raise DatabaseError("task result could not be recorded")

        self.process(on_saved=fail_result)
        self.assertFalse(JSONData.objects.exists())
        self.assertEqual(self.report["status"], "failed")
        self.assertEqual(self.report["saved_count"], 0)
        self.assertIn("save_error", self.report["issues"])
