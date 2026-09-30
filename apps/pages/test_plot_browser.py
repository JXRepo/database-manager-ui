import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import WSGIServer
from django.test import override_settings
from django.test.testcases import LiveServerThread, QuietWSGIRequestHandler
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData


class PlotLiveServerThread(LiveServerThread):
    """
    Serve browser checks using a single SQLite connection at a time
    """

    def _create_server(self, connections_override=None):
        """
        Avoid concurrent requests to the test database's shared connection

        Parameters
        ----------
        connections_override : dict or None
            Connections already installed by LiveServerThread.run.

        Returns
        -------
        WSGIServer
            Sequential server for the detail page checks.
        """
        return WSGIServer((self.host, self.port), QuietWSGIRequestHandler,
                          allow_reuse_address=False)


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class MechanicalPlotBrowserTests(StaticLiveServerTestCase):
    """
    Check plot quadrants, labels and exports in desktop Chromium
    """

    server_thread_class = PlotLiveServerThread

    def test_detail_plot_quadrants_and_existing_controls(self):
        """
        Draw all quadrant arrangements while preserving curve data and controls

        Synthetic signed curves cover the viewport rules. The local example,
        when present, adds a check using the user's actual array lengths.
        """
        self.assertTrue(shutil.which("node"), "Plot browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="plot-browser-viewer")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        cases = []
        arrangements = (
            ("first", [0, .01, .02], [0, 40, 80], "+", "+"),
            ("second", [-.01, -.02], [40, 80], "-", "+"),
            ("third", [-.01, -.02], [-40, -80], "-", "-"),
            ("fourth", [.01, .02], [-40, -80], "+", "-"),
            ("upper", [-.01, .02], [40, 80], "-+", "+"),
            ("lower", [-.01, .02], [-40, -80], "-+", "-"),
            ("left", [-.01, -.02], [-40, 80], "-", "-+"),
            ("right", [.01, .02], [-40, 80], "+", "-+"),
            ("diagonal-13", [.01, -.02], [40, -80], "-+", "-+"),
            ("diagonal-24", [-.01, .02], [40, -80], "-+", "-+"),
            ("three", [.01, -.02, -.01], [40, 80, -40], "-+", "-+"),
            ("cycle", [.01, -.02, -.01, .02, .01], [40, 80, -40, -80, 40], "-+", "-+"),
            ("zero", [0], [0], "+", "+"),
            ("small", [-2e-16, 3e-16], [-3e-14, 4e-14], "-+", "-+"),
        )
        for name, x_values, y_values, x_signs, y_signs in arrangements:
            obj = JSONData.objects.create(owner=viewer, data={
                "identifier": f"plot-{name}", "title": f"Mechanical response: {name}",
                "stress": {"stress_11": y_values, "stress_22": [0, 10, 20]},
                "total_strain": {"strain_11": x_values, "strain_22": [0, .1, .2]},
                "plastic_strain": {"plastic_strain_11": [0, .001, .004]},
                "units": {"Stress": "MPa", "Strain": 1},
            })
            cases.append({"name": name, "path": reverse("json_data_detail", args=[obj.pk]),
                          "x": x_values, "y": y_values, "xSigns": x_signs, "ySigns": y_signs})
        empty = JSONData.objects.create(owner=viewer, data={"title": "No curves " * 60})
        example = settings.BASE_DIR / "example_json_files/a46fde6c.json"
        sample_path = ""
        if example.is_file():
            sample = JSONData.objects.create(owner=viewer, data=json.loads(example.read_text()))
            sample_path = reverse("json_data_detail", args=[sample.pk])
        self.client.force_login(viewer)
        environment = dict(os.environ, PLOT_BASE_URL=self.live_server_url,
                           PLOT_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           PLOT_COOKIE_NAME=settings.SESSION_COOKIE_NAME, PLOT_CASES=json.dumps(cases),
                           PLOT_EMPTY_PATH=reverse("json_data_detail", args=[empty.pk]),
                           PLOT_SAMPLE_PATH=sample_path)
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/mechanical-plot.cjs")],
            env=environment, capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
