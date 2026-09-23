import logging
import os
import shutil
import time
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import DatabaseError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .forms import JSONUploadForm
from .models import UploadJob, UploadWorkerInstance
from .rate_limits import consume_rate_limit
from .upload_services import UploadResourceLimitError, validate_upload_files


logger = logging.getLogger(__name__)
ACTIVE_STATUSES = ("queued", "processing")
TERMINAL_STATUSES = ("completed", "interrupted", "rejected")
CONFIRMED_FILE_STATUSES = ("uploaded", "failed")


class UploadStopped(Exception):
    """
    Stop work whose lease, deadline or task ownership no longer permits saving
    """


def job_snapshot(job):
    """
    Expose only progress and results belonging to the authenticated owner

    Parameters
    ----------
    job : UploadJob
        Persisted submission.

    Returns
    -------
    dict
        Public task fields without staging paths or worker tokens.
    """
    fields = ("name", "status", "validated_count", "object_count", "saved_count")
    return {
        "id": str(job.pk), "submission_id": str(job.submission_id), "status": job.status,
        "files": [{key: item[key] for key in fields} for item in job.files],
        "summary": job.summary, "level": job.level, "report_html": job.report_html,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
    }


def _response(data, status=200):
    """
    Return private progress without allowing browser or proxy caching

    Parameters
    ----------
    data : dict
        Response payload.
    status : int, optional
        HTTP status.

    Returns
    -------
    JsonResponse
        Uncached response.
    """
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    return response


def staging_directory(job):
    """
    Derive a private directory exclusively from server controlled UUIDs

    Parameters
    ----------
    job : UploadJob
        Submission and originating service instance.

    Returns
    -------
    Path
        Directory below the configured staging root.
    """
    return Path(settings.UPLOAD_STAGING_ROOT) / str(job.instance_id) / str(job.pk)


def remove_staged_files(job):
    """
    Remove original files after processing without touching stored data objects

    Parameters
    ----------
    job : UploadJob
        Submission whose private files can be discarded.
    """
    shutil.rmtree(staging_directory(job), ignore_errors=True)


def _interrupt_locked(job, message):
    """
    Retain confirmed file results and mark all unfinished files unconfirmed

    Parameters
    ----------
    job : UploadJob
        Submission locked by the caller.
    message : str
        Clear interruption explanation.
    """
    from .views import _get_upload_issue_messages

    if job.status not in ACTIVE_STATUSES:
        return
    for item in job.files:
        if item["status"] not in CONFIRMED_FILE_STATUSES:
            item["status"] = "unconfirmed"
    job.status = "interrupted"
    job.summary = message
    job.level = "warning"
    confirmed = [item for item in job.files if item["status"] in CONFIRMED_FILE_STATUSES]
    reports = _get_upload_issue_messages(confirmed)
    job.report_html = reports[0] if reports else ""
    job.staged_bytes = 0
    job.save(update_fields=["status", "files", "summary", "level", "report_html", "staged_bytes", "updated_at"])


def interrupt_job(job_id, message):
    """
    Fence future writes before reporting an interrupted submission

    Parameters
    ----------
    job_id : UUID
        Submission to stop.
    message : str
        Interruption explanation.
    """
    with transaction.atomic():
        job = UploadJob.objects.select_for_update().filter(pk=job_id).first()
        if job is not None:
            _interrupt_locked(job, message)


def expire_upload_jobs(owner_id=None, job_id=None):
    """
    Mark abandoned work interrupted without reclaiming or retrying any task

    A fresh deployment must not interrupt jobs on the still running old instance.
    Row locks serialize expiry with each final file commit.

    Parameters
    ----------
    owner_id : int, optional
        Restrict request driven maintenance to its authenticated account.
    job_id : UUID, optional
        Restrict a detail request to one task.
    """
    candidates = UploadJob.objects.filter(status__in=ACTIVE_STATUSES)
    if owner_id is not None:
        candidates = candidates.filter(owner_id=owner_id)
    if job_id is not None:
        candidates = candidates.filter(pk=job_id)
    for candidate_id in candidates.values_list("pk", flat=True):
        with transaction.atomic():
            job = UploadJob.objects.select_for_update(skip_locked=True).filter(
                pk=candidate_id, status__in=ACTIVE_STATUSES,
            ).first()
            if job is None:
                continue
            now = timezone.now()
            cutoff = now - timedelta(seconds=settings.UPLOAD_WORKER_LEASE_SECONDS)
            expired = not UploadWorkerInstance.objects.filter(
                pk=job.instance_id, heartbeat_at__gte=cutoff,
            ).exists()
            expired = expired or bool(job.deadline_at and job.deadline_at <= now)
            expired = expired or (
                not job.ready and job.created_at <= now - timedelta(seconds=settings.UPLOAD_RECEIVING_MAX_SECONDS)
            )
            if expired:
                _interrupt_locked(job, "Upload interrupted. Confirmed results are retained; unfinished files were not retried.")


@login_required
@require_http_methods(["GET", "POST"])
def upload_jobs_view(request):
    """
    Receive one multipart submission or return the owner's latest upload

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with CSRF protection for submission.

    Returns
    -------
    JsonResponse
        Accepted task, latest status, or an actionable error.
    """
    try:
        expire_upload_jobs(owner_id=request.user.pk)
        if request.method == "GET":
            job = UploadJob.objects.filter(owner=request.user).order_by("-created_at").first()
            return _response({"job": job_snapshot(job) if job else None})
        return _receive_upload(request)
    except DatabaseError:
        logger.exception("Could not access upload task state")
        return _response({"error": "Uploading is temporarily unavailable. Check your upload status before submitting again."}, 503)


@login_required
@require_GET
def upload_job_view(request, job_id):
    """
    Return a task only to the account that submitted its files

    Parameters
    ----------
    request : HttpRequest
        Authenticated status request.
    job_id : UUID
        Requested submission.

    Returns
    -------
    JsonResponse
        Owner's status, or a non revealing not found response.
    """
    try:
        expire_upload_jobs(owner_id=request.user.pk, job_id=job_id)
        job = UploadJob.objects.filter(pk=job_id, owner=request.user).first()
        if job is None:
            return _response({"error": "Upload not found."}, 404)
        return _response({"job": job_snapshot(job)})
    except DatabaseError:
        return _response({"error": "Upload status is temporarily unavailable."}, 503)


def _receive_upload(request):
    """
    Reserve bounded private staging and acknowledge only fully received files

    Parameters
    ----------
    request : HttpRequest
        Multipart submission whose files are held by Django upload handlers.

    Returns
    -------
    JsonResponse
        Accepted job or rejection before data objects are saved.
    """
    from .views import _upload_label

    try:
        submission_id = uuid.UUID(request.POST.get("submission_id", ""))
    except (ValueError, TypeError, AttributeError):
        return _response({"error": "Reload the upload page before submitting files."}, 400)
    existing = UploadJob.objects.filter(owner=request.user, submission_id=submission_id).first()
    if existing:
        return _response({"job": job_snapshot(existing)}, 202)
    decision = consume_rate_limit("upload", str(request.user.pk))
    if not decision.allowed:
        response = _response({"error": "Too many upload attempts. Please wait before trying again."}, 429)
        response["Retry-After"] = str(decision.retry_after_seconds)
        return response
    form = JSONUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return _response({"error": " ".join(str(error) for errors in form.errors.values() for error in errors)}, 400)
    uploaded_files = form.cleaned_data["file"]
    try:
        validate_upload_files(uploaded_files, check_file_sizes=False)
        instance_id = uuid.UUID(settings.UPLOAD_INSTANCE_ID)
    except UploadResourceLimitError as error:
        return _response({"error": str(error)}, 400)
    except (ValueError, TypeError, AttributeError):
        return _response({"error": "Background uploads are temporarily unavailable."}, 503)
    total_bytes = sum(item.size for item in uploaded_files)
    reports = []
    for index, item in enumerate(uploaded_files):
        reports.append({
            "name": _upload_label(item.name) or "Uploaded file", "storage_name": f"{index}.json",
            "size": item.size, "status": "waiting", "validated_count": 0,
            "object_count": None, "saved_count": 0, "issues": {}, "objects": [],
        })
    with transaction.atomic():
        # A file save can hold this owner lock for longer than one heartbeat lease.
        # Wait for it before briefly locking the instance's staging reservation.
        User.objects.select_for_update().get(pk=request.user.pk)
        cutoff = timezone.now() - timedelta(seconds=settings.UPLOAD_WORKER_LEASE_SECONDS)
        worker = UploadWorkerInstance.objects.select_for_update().filter(
            pk=instance_id, heartbeat_at__gte=cutoff,
        ).first()
        if worker is None:
            return _response({"error": "Background uploads are temporarily unavailable."}, 503)
        existing = UploadJob.objects.filter(owner=request.user, submission_id=submission_id).first()
        if existing:
            return _response({"job": job_snapshot(existing)}, 202)
        active = UploadJob.objects.filter(owner=request.user, status__in=ACTIVE_STATUSES).first()
        if active:
            return _response({"error": "An upload is already in progress. Wait for its results before submitting more files.", "job": job_snapshot(active)}, 409)
        reserved = UploadJob.objects.filter(instance_id=instance_id, status__in=ACTIVE_STATUSES).aggregate(
            total=Sum("staged_bytes"),
        )["total"] or 0
        if reserved + total_bytes > settings.UPLOAD_STAGING_MAX_BYTES:
            return _response({"error": "Upload storage is busy. Wait for current uploads to finish before trying again."}, 503)
        job = UploadJob.objects.create(
            owner=request.user, submission_id=submission_id, instance_id=instance_id,
            files=reports, staged_bytes=total_bytes, summary="Receiving files for background processing.",
        )
    try:
        directory = staging_directory(job)
        Path(settings.UPLOAD_STAGING_ROOT).mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(settings.UPLOAD_STAGING_ROOT, 0o700)
        directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory.parent, 0o700)
        directory.mkdir(mode=0o700)
        if shutil.disk_usage(directory).free < total_bytes + settings.UPLOAD_STAGING_DISK_RESERVE_BYTES:
            raise OSError("Insufficient temporary upload storage")
        for item, report in zip(uploaded_files, reports):
            destination = directory / report["storage_name"]
            with destination.open("xb") as output:
                os.chmod(destination, 0o600)
                for chunk in item.chunks():
                    output.write(chunk)
        with transaction.atomic():
            current = UploadJob.objects.select_for_update().get(pk=job.pk)
            if current.status not in ACTIVE_STATUSES:
                raise UploadStopped
            current.ready = True
            current.summary = "Files received. Waiting for background processing."
            current.save(update_fields=["ready", "summary", "updated_at"])
            job = current
    except (OSError, UploadStopped, DatabaseError):
        interrupt_job(job.pk, "The server could not retain these files. No data objects were saved; select the files again to retry.")
        remove_staged_files(job)
        job.refresh_from_db()
        return _response({"error": job.summary, "job": job_snapshot(job)}, 503)
    return _response({"job": job_snapshot(job)}, 202)


def claim_upload_job(instance_id):
    """
    Claim one queued submission whose files exist on this service instance

    Parameters
    ----------
    instance_id : UUID
        Worker boot identity shared with its web processes.

    Returns
    -------
    UploadJob or None
        Claimed task with a unique write fence.
    """
    with transaction.atomic():
        job = UploadJob.objects.select_for_update(skip_locked=True).filter(
            instance_id=instance_id, status="queued", ready=True,
        ).order_by("created_at").first()
        if job is None:
            return None
        job.status = "processing"
        job.claim_token = uuid.uuid4()
        job.deadline_at = timezone.now() + timedelta(seconds=settings.UPLOAD_JOB_MAX_SECONDS)
        job.summary = "Checking the complete submission before saving data."
        job.save(update_fields=["status", "claim_token", "deadline_at", "summary", "updated_at"])
        return job


def _locked_job(job):
    """
    Recheck the write fence while holding a lock through the caller's transaction

    Parameters
    ----------
    job : UploadJob
        Claimed submission and token.

    Returns
    -------
    UploadJob
        Current locked state.

    Raises
    ------
    UploadStopped
        If the task was interrupted or exceeded its processing deadline.
    """
    current = UploadJob.objects.select_for_update().get(pk=job.pk)
    if current.status != "processing" or current.claim_token != job.claim_token:
        raise UploadStopped
    if current.deadline_at and current.deadline_at <= timezone.now():
        raise UploadStopped
    cutoff = timezone.now() - timedelta(seconds=settings.UPLOAD_WORKER_LEASE_SECONDS)
    if not UploadWorkerInstance.objects.filter(pk=current.instance_id, heartbeat_at__gte=cutoff).exists():
        raise UploadStopped
    return current


def _update_file(job, index, values):
    """
    Persist one real progress update or final file result behind the task fence

    Parameters
    ----------
    job : UploadJob
        Claimed submission.
    index : int
        Original file position.
    values : dict
        Fields changed by actual completed work.
    """
    with transaction.atomic():
        current = _locked_job(job)
        current.files[index].update(values)
        current.save(update_fields=["files", "updated_at"])


def _finish_job(job, status="completed", error=""):
    """
    Store a complete escaped result without deleting already committed objects

    Parameters
    ----------
    job : UploadJob
        Claimed submission.
    status : str, optional
        Completed or rejected terminal state.
    error : str, optional
        Batch precheck rejection.
    """
    from .views import _get_upload_issue_messages

    with transaction.atomic():
        current = _locked_job(job)
        count = sum(item["status"] == "uploaded" for item in current.files)
        failed = len(current.files) - count
        if error:
            for item in current.files:
                if item["status"] != "uploaded":
                    item["status"] = "failed"
            summary, level = error, "error"
        elif failed:
            summary = f"Upload finished: {count} file(s) uploaded, {failed} file(s) failed."
            level = "warning" if count else "error"
        else:
            objects = sum(item["saved_count"] for item in current.files)
            summary = f"Upload successful: {objects} data object(s) saved from {count} file(s)."
            level = "success"
        reports = _get_upload_issue_messages(current.files)
        current.status = status
        current.summary = summary
        current.level = level
        current.report_html = reports[0] if reports else ""
        current.staged_bytes = 0
        current.save(update_fields=["status", "files", "summary", "level", "report_html", "staged_bytes", "updated_at"])


def process_upload_job(job):
    """
    Precheck every file, then validate and atomically save files in original order

    Parameters
    ----------
    job : UploadJob
        Submission already claimed by this worker.
    """
    from .views import _inspect_upload_file, _process_upload_file

    inspections = {}
    count = 0
    saved_identifiers = set()
    try:
        for index, report in enumerate(job.files):
            _update_file(job, index, {"status": "parsing"})
            with (staging_directory(job) / report["storage_name"]).open("rb") as source:
                uploaded = UploadedFile(source, name=report["name"], size=report["size"])
                inspection = _inspect_upload_file(uploaded, report)
            if inspection is not None:
                object_count, depth = inspection
                count += object_count
                report["object_count"] = object_count
                inspections[index] = depth
            _update_file(job, index, {**report, "status": "waiting"})
        if count > settings.PILOT_MAX_UPLOAD_OBJECTS:
            _finish_job(job, "rejected", "The upload exceeds the maximum number of JSON data objects. No files were saved.")
            return

        for index, report in enumerate(job.files):
            if index not in inspections:
                _update_file(job, index, {**report, "status": "failed"})
                continue

            last_progress = {"time": 0, "stage": ""}

            def progress(stage, completed, total):
                """
                Record completed object checks without predicting saved objects

                Parameters
                ----------
                stage : str
                    Current processing phase.
                completed : int
                    Objects whose validation has finished.
                total : int
                    Known object count.
                """
                now = time.monotonic()
                if (stage == last_progress["stage"] and completed not in (0, total)
                        and now - last_progress["time"] < 0.5):
                    return
                _update_file(job, index, {
                    "status": stage, "validated_count": completed, "object_count": total,
                })
                last_progress.update(time=now, stage=stage)

            def on_saved(file_report):
                """
                Commit the file result inside the data object's outer transaction

                Parameters
                ----------
                file_report : dict
                    Final file result from the existing atomic save workflow.
                """
                _update_file(job, index, {**file_report, "validated_count": report["object_count"]})

            with (staging_directory(job) / report["storage_name"]).open("rb") as source:
                uploaded = UploadedFile(source, name=report["name"], size=report["size"])
                _process_upload_file(
                    job.owner, report, uploaded, inspections[index], saved_identifiers,
                    progress=progress, on_saved=on_saved,
                )
            if report["status"] != "uploaded":
                _update_file(job, index, {**report, "status": "failed", "validated_count": report["object_count"]})
        _finish_job(job)
    except UploadStopped:
        interrupt_job(job.pk, "Upload interrupted. Confirmed results are retained; unfinished files were not retried.")
    except Exception:
        logger.exception("Upload worker could not complete task %s", job.pk)
        interrupt_job(job.pk, "Upload interrupted by a service error. Confirmed results are retained; unfinished files were not retried.")
    finally:
        remove_staged_files(job)


def cleanup_upload_jobs(instance_id):
    """
    Expire abandoned tasks and discard terminal local originals and old reports

    Parameters
    ----------
    instance_id : UUID
        Current worker's local staging namespace.
    """
    expire_upload_jobs()
    for job in UploadJob.objects.filter(status__in=TERMINAL_STATUSES):
        remove_staged_files(job)
    cutoff = timezone.now() - timedelta(days=settings.UPLOAD_RESULT_RETENTION_DAYS)
    UploadJob.objects.filter(status__in=TERMINAL_STATUSES, updated_at__lt=cutoff).delete()
    root = Path(settings.UPLOAD_STAGING_ROOT)
    orphan_cutoff = timezone.now().timestamp() - settings.UPLOAD_RECEIVING_MAX_SECONDS
    if root.is_dir():
        for instance_dir in root.iterdir():
            if not instance_dir.is_dir() or instance_dir.is_symlink():
                continue
            try:
                uuid.UUID(instance_dir.name)
            except ValueError:
                continue
            for directory in instance_dir.iterdir():
                if not directory.is_dir() or directory.is_symlink():
                    continue
                try:
                    candidate_id = uuid.UUID(directory.name)
                except ValueError:
                    continue
                try:
                    old_directory = directory.stat().st_mtime < orphan_cutoff
                except FileNotFoundError:
                    continue
                if old_directory and not UploadJob.objects.filter(pk=candidate_id).exists():
                    shutil.rmtree(directory, ignore_errors=True)
