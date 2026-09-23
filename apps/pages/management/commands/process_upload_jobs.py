import logging
import signal
import threading
import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections, connections
from django.utils import timezone

from apps.pages.models import UploadWorkerInstance
from apps.pages.upload_jobs import claim_upload_job, cleanup_upload_jobs, process_upload_job


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Process this service instance's upload queue independently of web requests
    """

    help = "Process local staged uploads without automatically retrying interrupted jobs"

    def add_arguments(self, parser):
        """
        Add a bounded execution option for local checks

        Parameters
        ----------
        parser : ArgumentParser
            Django command argument parser.
        """
        parser.add_argument("--once", action="store_true", help="Process at most one queued submission")

    def handle(self, *args, **options):
        """
        Maintain a heartbeat while the worker handles one submission at a time

        Parameters
        ----------
        *args : tuple
            Positional command arguments.
        **options : dict
            Django command options.
        """
        try:
            instance_id = uuid.UUID(settings.UPLOAD_INSTANCE_ID)
        except (ValueError, TypeError, AttributeError) as error:
            raise CommandError("UPLOAD_INSTANCE_ID must identify the shared web and upload worker instance") from error

        stopping = threading.Event()

        def stop_worker(signum, frame):
            """
            Stop claiming new jobs while allowing the current transaction to finish

            Parameters
            ----------
            signum : int
                Received termination signal.
            frame : frame or None
                Interrupted Python frame.
            """
            stopping.set()

        def heartbeat():
            """
            Keep instance liveness independent of parsing and database saving
            """
            try:
                while not stopping.wait(5):
                    try:
                        close_old_connections()
                        UploadWorkerInstance.objects.filter(pk=instance_id).update(heartbeat_at=timezone.now())
                    except DatabaseError:
                        logger.warning("Upload worker heartbeat could not reach the database")
            finally:
                connections.close_all()

        previous = {}
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, stop_worker)
        UploadWorkerInstance.objects.update_or_create(
            pk=instance_id, defaults={"heartbeat_at": timezone.now()},
        )
        thread = None
        if not options["once"]:
            thread = threading.Thread(target=heartbeat, name="upload-heartbeat", daemon=True)
            thread.start()
        try:
            last_cleanup = 0
            while not stopping.is_set():
                close_old_connections()
                if time.monotonic() - last_cleanup >= 30:
                    cleanup_upload_jobs(instance_id)
                    last_cleanup = time.monotonic()
                job = claim_upload_job(instance_id)
                if job is not None:
                    process_upload_job(job)
                if options["once"]:
                    break
                if job is None:
                    stopping.wait(1)
        finally:
            stopping.set()
            if thread:
                thread.join(timeout=6)
            UploadWorkerInstance.objects.filter(pk=instance_id).delete()
            cleanup_upload_jobs(instance_id)
            for signum, handler in previous.items():
                signal.signal(signum, handler)
