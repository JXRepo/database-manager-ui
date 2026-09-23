import copy
import json
import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DataNotification, JSONData, RateLimitBucket, UploadJob, UploadWorkerInstance
from .upload_jobs import (
    _update_file, claim_upload_job, cleanup_upload_jobs, expire_upload_jobs,
    interrupt_job, process_upload_job, staging_directory,
)


class UploadJobTests(TestCase):
    """
    Verify durable results, private staging and atomic background file saves
    """

    def setUp(self):
        """
        Create an isolated live worker namespace and authenticated uploader
        """
        self.owner = User.objects.create_user("job-owner")
        self.other = User.objects.create_user("job-other")
        self.client.force_login(self.owner)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.instance_id = uuid.uuid4()
        self.settings = override_settings(
            UPLOAD_INSTANCE_ID=str(self.instance_id), UPLOAD_STAGING_ROOT=Path(self.directory.name),
            UPLOAD_STAGING_DISK_RESERVE_BYTES=0,
        )
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        UploadWorkerInstance.objects.create(id=self.instance_id, heartbeat_at=timezone.now())
        self.example = {
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

    def data(self, title):
        """
        Build one complete independent object

        Parameters
        ----------
        title : str
            Distinct title used in the generated content fingerprint.

        Returns
        -------
        dict
            Valid upload metadata.
        """
        result = copy.deepcopy(self.example)
        result["title"] = title
        return result

    def submit(self, *payloads, submission_id=None):
        """
        Send exactly one multipart request containing the ordered inputs

        Parameters
        ----------
        *payloads : object
            JSON content or deliberately unreadable bytes.
        submission_id : UUID, optional
            Existing client token for duplicate submission checks.

        Returns
        -------
        HttpResponse
            JSON task acceptance or rejection.
        """
        files = []
        for payload in payloads:
            content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            files.append(SimpleUploadedFile("same.json", content, content_type="application/json"))
        return self.client.post(reverse("upload_jobs"), {
            "submission_id": str(submission_id or uuid.uuid4()), "file": files,
        })

    def process(self):
        """
        Process the next local task and return its persisted terminal state

        Returns
        -------
        UploadJob
            Most recently processed submission.
        """
        job = claim_upload_job(self.instance_id)
        self.assertIsNotNone(job)
        process_upload_job(job)
        job.refresh_from_db()
        return job

    def test_navigation_and_new_page_recover_one_hundred_confirmed_objects(self):
        """
        Keep processing independent of the request and retain accurate object counts
        """
        response = self.submit([self.data(f"Object {index}") for index in range(100)])
        self.assertEqual(response.status_code, 202)
        snapshot = response.json()["job"]
        self.assertEqual(snapshot["status"], "queued")
        self.assertTrue(snapshot["submission_id"])
        self.assertFalse(JSONData.objects.exists())
        self.assertEqual(self.client.get(reverse("search")).status_code, 200)

        with patch("apps.pages.upload_jobs._update_file", wraps=_update_file) as updates:
            job = self.process()
        self.assertEqual(job.status, "completed")
        self.assertEqual(JSONData.objects.count(), 100)
        self.assertEqual(job.files[0]["validated_count"], 100)
        self.assertEqual(job.files[0]["saved_count"], 100)
        self.assertLess(updates.call_count, 30)
        recovered = self.client.get(reverse("upload_job", args=[job.pk])).json()["job"]
        self.assertEqual(recovered["files"][0]["status"], "uploaded")
        self.assertEqual(recovered["submission_id"], snapshot["submission_id"])
        self.assertNotIn("storage_name", recovered["files"][0])
        self.assertFalse(staging_directory(job).exists())

    @override_settings(PILOT_MAX_UPLOAD_OBJECTS=2)
    def test_batch_object_limit_prevents_every_file_save(self):
        """
        Count all readable files before persisting the first valid object
        """
        self.assertEqual(self.submit(self.data("one"), [self.data("two"), self.data("three")]).status_code, 202)
        job = self.process()
        self.assertEqual(job.status, "rejected")
        self.assertFalse(JSONData.objects.exists())
        self.assertIn("maximum number", job.summary)

    def test_file_count_and_combined_byte_limits_precede_staging(self):
        """
        Reject request resource limits without creating a background task
        """
        with override_settings(PILOT_MAX_UPLOAD_FILES=1):
            self.assertEqual(self.submit(self.data("one"), self.data("two")).status_code, 400)
        with override_settings(PILOT_MAX_UPLOAD_REQUEST_BYTES=10):
            self.assertEqual(self.submit(self.data("one")).status_code, 400)
        self.assertFalse(UploadJob.objects.exists())
        self.assertFalse(JSONData.objects.exists())

    def test_readable_errors_reject_whole_file_and_other_files_continue(self):
        """
        Keep grouped field errors while saving independently valid later files
        """
        missing = self.data("Missing phase")
        del missing["phase"]
        empty = self.data("<script>empty</script>")
        empty["creator"] = ""
        self.submit([missing, empty, self.data("Valid but same rejected file")], self.data("Later valid file"))
        job = self.process()
        self.assertEqual([item["status"] for item in job.files], ["failed", "uploaded"])
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertIn("phase", job.report_html)
        self.assertIn("creator", job.report_html)
        self.assertIn("&lt;script&gt;", job.report_html)
        self.assertNotIn("<script>", job.report_html)

    def test_invalid_json_and_file_size_are_local_to_each_file(self):
        """
        Retain each file failure and continue with the valid file
        """
        good = self.data("Accepted")
        limit = len(json.dumps(good).encode()) + 10
        with override_settings(PILOT_MAX_UPLOAD_FILE_BYTES=limit):
            self.submit(b"not json", b"x" * (limit + 1), good)
            job = self.process()
        self.assertEqual([item["status"] for item in job.files], ["failed", "failed", "uploaded"])
        self.assertEqual(JSONData.objects.count(), 1)

    def test_owner_access_and_duplicate_submission_do_not_create_a_second_job(self):
        """
        Restrict task details and recover a repeated client token without resaving
        """
        submission_id = uuid.uuid4()
        response = self.submit(self.data("one"), submission_id=submission_id)
        job_id = response.json()["job"]["id"]
        repeated = self.submit(self.data("one"), submission_id=submission_id)
        self.assertEqual(repeated.json()["job"]["id"], job_id)
        self.assertEqual(UploadJob.objects.count(), 1)
        self.assertEqual(RateLimitBucket.objects.get(scope="upload").count, 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("upload_job", args=[job_id])).status_code, 404)
        self.assertIsNone(self.client.get(reverse("upload_jobs")).json()["job"])

    def test_only_one_active_submission_per_owner_and_storage_is_bounded(self):
        """
        Refuse overlapping work and staging beyond the configured instance budget
        """
        self.assertEqual(self.submit(self.data("one")).status_code, 202)
        self.assertEqual(self.submit(self.data("two")).status_code, 409)
        self.client.force_login(self.other)
        with override_settings(UPLOAD_STAGING_MAX_BYTES=1):
            self.assertEqual(self.submit(self.data("three")).status_code, 503)
        self.assertEqual(UploadJob.objects.count(), 1)

    def test_private_files_use_internal_names_and_permissions(self):
        """
        Keep original uploaded text out of filesystem paths and public responses
        """
        self.submit(self.data("one"), self.data("two"))
        job = UploadJob.objects.get()
        directory = staging_directory(job)
        self.assertEqual(sorted(item.name for item in directory.iterdir()), ["0.json", "1.json"])
        if os.name == "posix":
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / "0.json").stat().st_mode & 0o777, 0o600)

    def test_result_write_failure_rolls_back_data_and_notifications(self):
        """
        Never confirm saved objects unless their file result commits atomically
        """
        data = self.data("Shared object")
        data["shared_with"] = [{"access_type": "c", "username": self.other.username}]
        self.submit(data)

        def fail_result(job, index, values):
            """
            Fail only after the object save has executed inside its transaction

            Parameters
            ----------
            job : UploadJob
                Active task.
            index : int
                File index.
            values : dict
                Attempted progress update.
            """
            if values.get("status") == "uploaded":
                self.assertTrue(JSONData.objects.exists())
                self.assertTrue(DataNotification.objects.exists())
                raise OperationalError("result write failed")
            return _update_file(job, index, values)

        with patch("apps.pages.upload_jobs._update_file", side_effect=fail_result):
            job = self.process()
        self.assertFalse(JSONData.objects.exists())
        self.assertFalse(DataNotification.objects.exists())
        self.assertEqual(job.files[0]["status"], "failed")

    def test_expired_fence_prevents_late_file_commit(self):
        """
        Roll back work that reaches saving after its task was interrupted
        """
        self.submit(self.data("one"))

        def interrupt_before_save(job, index, values):
            """
            Invalidate the claim immediately before the existing save transaction

            Parameters
            ----------
            job : UploadJob
                Active task.
            index : int
                File index.
            values : dict
                Actual progress update.
            """
            result = _update_file(job, index, values)
            if values.get("status") == "saving":
                interrupt_job(job.pk, "Interrupted by test")
            return result

        with patch("apps.pages.upload_jobs._update_file", side_effect=interrupt_before_save):
            job = self.process()
        self.assertEqual(job.status, "interrupted")
        self.assertFalse(JSONData.objects.exists())
        self.assertIsNone(claim_upload_job(self.instance_id))

    def test_interruption_preserves_confirmed_failure_details(self):
        """
        Keep a failed file's escaped errors when a later file loses its staging
        """
        self.submit(b"not json", self.data("two"))
        original = _update_file

        def remove_later_file(job, index, values):
            """
            Simulate a missing staged file after the first result was confirmed

            Parameters
            ----------
            job : UploadJob
                Active task.
            index : int
                Current file index.
            values : dict
                Progress update being persisted.
            """
            original(job, index, values)
            if index == 0 and values.get("status") == "failed":
                (staging_directory(job) / "1.json").unlink()

        with patch("apps.pages.upload_jobs._update_file", side_effect=remove_later_file):
            with self.assertLogs("apps.pages.upload_jobs", level="ERROR"):
                job = self.process()
        self.assertEqual(job.status, "interrupted")
        self.assertEqual(job.files[0]["status"], "failed")
        self.assertIn("Invalid JSON file", job.report_html)

    def test_rolling_deploy_isolates_live_instances_and_never_retries_stale_work(self):
        """
        Leave the previous live instance alone and expire it only after heartbeat loss
        """
        self.submit(self.data("one"))
        other_instance = uuid.uuid4()
        UploadWorkerInstance.objects.create(id=other_instance, heartbeat_at=timezone.now())
        self.assertIsNone(claim_upload_job(other_instance))
        expire_upload_jobs()
        self.assertEqual(UploadJob.objects.get().status, "queued")
        UploadWorkerInstance.objects.filter(pk=self.instance_id).update(
            heartbeat_at=timezone.now() - timedelta(minutes=5),
        )
        expire_upload_jobs()
        job = UploadJob.objects.get()
        self.assertEqual(job.status, "interrupted")
        self.assertEqual(job.files[0]["status"], "unconfirmed")
        UploadWorkerInstance.objects.filter(pk=self.instance_id).update(heartbeat_at=timezone.now())
        self.assertIsNone(claim_upload_job(self.instance_id))
        cleanup_upload_jobs(other_instance)
        self.assertFalse(staging_directory(job).exists())

    def test_missing_worker_is_rejected_without_staging(self):
        """
        Avoid accepting jobs when no local process can handle their files
        """
        UploadWorkerInstance.objects.all().delete()
        self.assertEqual(self.submit(self.data("one")).status_code, 503)
        self.assertFalse(UploadJob.objects.exists())

    def test_submit_requires_csrf_and_status_requires_login(self):
        """
        Enforce authentication and CSRF on the new upload endpoints
        """
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("upload_jobs"), {"submission_id": str(uuid.uuid4())}).status_code, 403)
        client.logout()
        self.assertEqual(client.get(reverse("upload_jobs")).status_code, 302)

    def test_management_worker_once_commits_and_cleans_up(self):
        """
        Exercise the actual management command against a received task
        """
        self.submit(self.data("one"))
        call_command("process_upload_jobs", once=True)
        job = UploadJob.objects.get()
        self.assertEqual(job.status, "completed")
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertFalse(staging_directory(job).exists())

    def test_old_results_expire_without_deleting_saved_data(self):
        """
        Remove old task reports while retaining their user's committed objects
        """
        self.submit(self.data("one"))
        job = self.process()
        UploadJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(days=8))
        cleanup_upload_jobs(self.instance_id)
        self.assertFalse(UploadJob.objects.exists())
        self.assertEqual(JSONData.objects.count(), 1)
