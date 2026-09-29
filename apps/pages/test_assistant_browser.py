import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import WSGIServer
from django.test import Client, override_settings
from django.test.testcases import LiveServerThread, QuietWSGIRequestHandler
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData
from .upload_test_data import valid_upload_object


class AssistantLiveServerThread(LiveServerThread):
    """
    Serialize browser requests that share one in-memory SQLite connection
    """

    def _create_server(self, connections_override=None):
        """
        Serve UI checks without concurrent access to SQLite's statement cache

        Parameters
        ----------
        connections_override : dict or None
            Connections already installed by LiveServerThread.run.

        Returns
        -------
        WSGIServer
            Sequential HTTP server for this browser test.
        """
        return WSGIServer((self.host, self.port), QuietWSGIRequestHandler,
                          allow_reuse_address=False)


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class AssistantBrowserTests(StaticLiveServerTestCase):
    """
    Verify the help widget against real HTTP responses in desktop Chromium
    """

    server_thread_class = AssistantLiveServerThread

    def test_help_navigation_and_desktop_layout(self):
        """
        Exercise semantic questions, long replies and conversation recovery
        """
        self.assertTrue(shutil.which("node"), "Assistant browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="assistant-browser-viewer")
        empty = User.objects.create_user(username="assistant-browser-empty")
        for user in (viewer, empty):
            AccountProfile.objects.create(user=user, getting_started_dismissed_at=timezone.now())
        obj = JSONData.objects.create(owner=viewer, data=valid_upload_object(
            identifier="assistant-browser-object",
            title='<img src=x onerror="window.assistantInjected=true">' + "LongTitle" * 350,
            stress={}, total_strain={},
        ))
        self.client.force_login(viewer)
        empty_client = Client()
        empty_client.force_login(empty)
        environment = dict(
            os.environ, ASSISTANT_BASE_URL=self.live_server_url,
            ASSISTANT_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            ASSISTANT_EMPTY_SESSION=empty_client.cookies[settings.SESSION_COOKIE_NAME].value,
            ASSISTANT_COOKIE_NAME=settings.SESSION_COOKIE_NAME,
            ASSISTANT_DETAIL_PATH=reverse("json_data_detail", args=[obj.pk]),
            ASSISTANT_EMPTY_PATH=reverse("json_data_list"),
        )
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/assistant.cjs")],
            env=environment, capture_output=True, text=True, timeout=90, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
