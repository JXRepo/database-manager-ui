import os
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path


worker_class = "gthread"
threads = 4
preload_app = False


def on_starting(server):
    """
    Give this web service and its upload processor one fresh instance identity

    Gunicorn reads this file automatically with the existing Render start command.
    A fresh identity prevents a new deployment from claiming another instance's
    temporary files or repeating its interrupted work.

    Parameters
    ----------
    server : Arbiter
        Gunicorn master process before application workers are forked.
    """
    os.environ["UPLOAD_INSTANCE_ID"] = str(uuid.uuid4())
    server.upload_stopping = threading.Event()
    server.upload_worker = None


def _watch_upload_worker(server):
    """
    Stop the web service if its background processor exits unexpectedly

    Parameters
    ----------
    server : Arbiter
        Master that supervises the upload process.
    """
    code = server.upload_worker.wait()
    if not server.upload_stopping.is_set():
        server.log.error("Upload processor exited with code %s; stopping the web service", code)
        os.kill(server.pid, signal.SIGTERM)


def when_ready(server):
    """
    Run the upload processor independently from web requests

    Parameters
    ----------
    server : Arbiter
        Listening Gunicorn master with its boot identity configured.
    """
    server.upload_worker = subprocess.Popen(
        [sys.executable, "manage.py", "process_upload_jobs"],
        cwd=Path(__file__).resolve().parent,
    )
    monitor = threading.Thread(target=_watch_upload_worker, args=(server,), daemon=True)
    monitor.start()


def on_exit(server):
    """
    Stop the processor with the web service and bound its shutdown time

    Parameters
    ----------
    server : Arbiter
        Master leaving normally or after a worker failure.
    """
    server.upload_stopping.set()
    worker = server.upload_worker
    if worker is None or worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=5)
