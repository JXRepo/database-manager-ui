from html import unescape

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils.html import strip_tags

from .forms import JSONUploadForm


class UploadLimitsDisplayTests(SimpleTestCase):
    """
    Keep the upload page aligned with active application allowances
    """

    def _page_text(self):
        """
        Render readable upload text without a database connection

        Returns
        -------
        str
            Page text with template markup and extra whitespace removed.
        """
        html = render_to_string("pages/upload.html", {"form": JSONUploadForm()})
        return " ".join(unescape(strip_tags(html)).split())

    def test_limits_follow_settings_changes_after_an_earlier_render(self):
        """
        Changed allowances replace the displayed values on the next render
        """
        self._page_text()

        with override_settings(
            PILOT_MAX_UPLOAD_FILES=7,
            PILOT_MAX_UPLOAD_FILE_BYTES=12 * 1024 * 1024,
            PILOT_MAX_UPLOAD_REQUEST_BYTES=36 * 1024 * 1024,
            PILOT_MAX_UPLOAD_OBJECTS=2345,
            PILOT_MAX_JSON_DEPTH=48,
            PILOT_MAX_USER_JSON_BYTES=3 * 1024 * 1024 * 1024,
            PILOT_RATE_LIMITS={"upload": {"limit": 8, "window_seconds": 1800}},
        ):
            text = self._page_text()

        for expected in (
            "up to 7 JSON files",
            "7 files",
            "12 MiB per file",
            "36 MiB combined",
            "2,345 objects",
            "48 container levels",
            "3 GiB of stored JSON",
            "8 upload attempts per 30 minutes",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    @override_settings(
        PILOT_MAX_UPLOAD_FILE_BYTES=1536 * 1024,
        PILOT_RATE_LIMITS={"upload": {"limit": 4, "window_seconds": 45}},
    )
    def test_fractional_binary_sizes_and_short_windows_stay_accurate(self):
        """
        Display fractional sizes and second based windows without rounding up
        """
        text = self._page_text()

        self.assertIn("1.5 MiB per file", text)
        self.assertIn("4 upload attempts per 45 seconds", text)

    @override_settings(UPLOAD_INSTANCE_ID="")
    def test_runserver_keeps_the_ordinary_streaming_upload(self):
        """
        Leave background submission disabled without a supervised worker
        """
        html = render_to_string("pages/upload.html", {"form": JSONUploadForm()})

        self.assertNotIn("data-jobs-url", html)
        self.assertNotIn("Background processing:", html)

    @override_settings(
        UPLOAD_INSTANCE_ID="12345678-1234-5678-1234-567812345678",
        UPLOAD_JOB_MAX_SECONDS=2700,
    )
    def test_background_upload_route_and_processing_allowance_follow_settings(self):
        """
        Enable supervised submissions and disclose their actual time allowance
        """
        html = render_to_string("pages/upload.html", {"form": JSONUploadForm()})
        text = self._page_text()

        self.assertIn('data-jobs-url="/upload/jobs/"', html)
        self.assertIn("1 active submission per account", text)
        self.assertIn("45 minutes processing time per submission", text)
