import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class PasswordRecoveryBrowserTests(StaticLiveServerTestCase):
    """
    Follow actual recovery emails and forms in desktop Chromium
    """

    server_thread_class = PlotLiveServerThread

    def test_email_link_password_update_and_login(self):
        """
        Recover through the login link with and without page JavaScript

        The file email backend captures test messages outside the repository.
        No external recipient or provider is contacted.
        """
        self.assertTrue(shutil.which("node"), "Password recovery browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        cases = []
        for width, javascript in ((1280, True), (1920, False)):
            username = f"recovery-browser-{width}"
            user = User.objects.create_user(username=username, email=f"{username}@example.org",
                                            password="OriginalQuartz!47River")
            cases.append({"username": username, "email": user.email,
                          "width": width, "javascript": javascript})
        with TemporaryDirectory(prefix="recovery-mail-") as mail_directory:
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend",
                EMAIL_FILE_PATH=mail_directory,
                DEFAULT_FROM_EMAIL="Materials Platform <accounts@example.org>",
                PASSWORD_RESET_BASE_URL="",
            ):
                result = subprocess.run(
                    [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/password-reset.cjs")],
                    env=dict(os.environ, RESET_BASE_URL=self.live_server_url,
                             RESET_MAIL_DIR=mail_directory, RESET_CASES=json.dumps(cases)),
                    capture_output=True, text=True, timeout=90, check=False,
                )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for case in cases:
            user = User.objects.get(username=case["username"])
            self.assertTrue(user.check_password("Copper!Meadow58Orchard"))
            self.assertFalse(user.check_password("OriginalQuartz!47River"))
        print(result.stdout)
