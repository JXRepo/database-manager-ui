import importlib.util
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from django.test import SimpleTestCase


class UploadSupervisionTests(SimpleTestCase):
    """
    Verify the existing Gunicorn command also supervises background uploads
    """

    def setUp(self):
        """
        Load the automatically discovered deployment configuration
        """
        path = Path(__file__).resolve().parents[2] / "gunicorn.conf.py"
        self.assertTrue(path.exists(), "Gunicorn needs its automatic upload worker configuration")
        spec = importlib.util.spec_from_file_location("upload_gunicorn_config", path)
        self.config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.config)
        self.server = SimpleNamespace(pid=987654, log=Mock())

    def test_existing_command_starts_worker_with_shared_instance_and_stops_it(self):
        """
        Keep web and background process identities aligned without dashboard edits
        """
        with patch.dict(os.environ, {}, clear=False), patch.object(self.config.subprocess, "Popen") as start:
            with patch.object(self.config.threading, "Thread"):
                self.config.on_starting(self.server)
                instance = os.environ["UPLOAD_INSTANCE_ID"]
                self.assertEqual(str(UUID(instance)), instance)
                self.config.when_ready(self.server)
            arguments = start.call_args.args[0]
            self.assertEqual(arguments[1:], ["manage.py", "process_upload_jobs"])
            self.assertEqual(Path(start.call_args.kwargs["cwd"]), Path(__file__).resolve().parents[2])
            worker = start.return_value
            worker.poll.return_value = None
            self.config.on_exit(self.server)
            worker.terminate.assert_called_once()
            worker.wait.assert_called_once()
            self.assertTrue(self.server.upload_stopping.is_set())
            self.assertEqual(self.config.worker_class, "gthread")
            self.assertGreaterEqual(self.config.threads, 2)

    def test_unexpected_worker_exit_stops_service_instead_of_accepting_silent_jobs(self):
        """
        Stop a service whose processor has died so its hosting restart can recover
        """
        with patch.dict(os.environ, {}, clear=False):
            self.config.on_starting(self.server)
        self.server.upload_worker = Mock()
        self.server.upload_worker.wait.return_value = 1
        with patch.object(self.config.os, "kill") as kill:
            self.config._watch_upload_worker(self.server)
            kill.assert_called_once_with(self.server.pid, signal.SIGTERM)
            self.server.upload_stopping.set()
            self.config._watch_upload_worker(self.server)
            self.assertEqual(kill.call_count, 1)

    def test_shutdown_forces_a_stuck_processor_to_exit(self):
        """
        Bound shutdown time when a background request cannot finish
        """
        with patch.dict(os.environ, {}, clear=False):
            self.config.on_starting(self.server)
        worker = self.server.upload_worker = Mock()
        worker.poll.return_value = None
        worker.wait.side_effect = [subprocess.TimeoutExpired("worker", 10), 0]
        self.config.on_exit(self.server)
        worker.kill.assert_called_once()
