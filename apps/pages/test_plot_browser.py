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
            ("away-from-zero", [10, 10.5, 11], [102, 100, 101], "+", "+"),
            ("near-endpoint", [0, .00110001], [0, 90], "+", "+"),
            ("wide-endpoints", [0, .00110001], [0, .00110001], "+", "+"),
            ("near-zero-reversal", [-5e-4, -1e-4, 9e-8], [-1.4e-5, -3e-6, 1.7e-13], "-+", "-+"),
            ("near-zero-negative-reversal", [5e-4, 1e-4, -9e-8], [1.4e-5, 3e-6, -1.7e-13], "-+", "-+"),
            ("narrow-offset", [1e8, 1e8 + .001, 1e8 + .002],
             [2e8, 2e8 + .002, 2e8 + .001], "+", "+"),
            ("constant-x", [2, 2, 2], [10, 30, 20], "+", "+"),
            ("constant-y", [-3, -2, -1], [-2, -2, -2], "-", "-"),
            ("long-decimal-upper", [0, .123456789], [0, 1234.567891234], "+", "+"),
            ("wide-negative-ticks", [-9999.99, 0], [-9999.99, 0], "-", "-"),
            ("half-up-ticks", [0, .005, .015, .025], [0, 1.005, 2.675, 3.005], "+", "+"),
            ("negative-half-up", [-.025, -.015, -.005], [-3.005, -2.675, -1.005], "-", "-"),
            ("scientific-bounds", [-.000123456789, .000987654321],
             [-123456789, 987654321], "-+", "-+"),
            ("scientific-positive", [0, 1.005e-8, 2.675e-8], [0, 1.005e9, 2.675e9], "+", "+"),
            ("scientific-second", [-2.675e-8, -1.005e-8, 0], [2.675e9, 1.005e9, 0], "-", "+"),
            ("scientific-fourth", [0, 1.005e-8, 2.675e-8], [0, -1.005e9, -2.675e9], "+", "-"),
            ("symmetric-scientific", [-.0012345, .0012345], [-1, 1], "-+", "-+"),
            ("symmetric-negative-y", [-.0012345, .0012345], [-1, -.5], "-+", "-"),
            ("corner-multipliers", [-9e-5, 1e-5], [-9e-5, 1e-5], "-+", "-+"),
            ("corner-multipliers-lower", [-9e-4, 1e-4], [-1e-5, 0], "-+", "-"),
            ("hundredths", [0, .02, .04, .07], [0, 20, 40, 80], "+", "+"),
            ("fractional-hundredth-step", [0, .175], [0, 80], "+", "+"),
            ("independent-exponents", [-.00014, -.0001, -.00002],
             [-1.4e7, -1e7, -2e6], "-", "-"),
        )
        expected_exponents = {
            "hundredths": {"x": None, "y": None},
            "fractional-hundredth-step": {"x": -1, "y": None},
            "independent-exponents": {"x": -4, "y": 7},
        }
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
            if name in expected_exponents:
                cases[-1]["exponents"] = expected_exponents[name]
        # Exact first 25 component-33 samples from a46fde6c.json, available offline.
        initial_x = [
            -5.4738439099200065e-06, -1.09477488051124e-05, -1.6421714229442053e-05,
            -2.1895741545596703e-05, -2.736982984263836e-05, -3.284397730002331e-05,
            -3.831818755423155e-05, -4.379245878477489e-05, -4.9266787352397756e-05,
            -5.47411805312259e-05, -6.0215634681837216e-05, -6.569014980289944e-05,
            -7.116472953061503e-05, -7.663935931251364e-05, -8.211405369812352e-05,
            -8.758881268583485e-05, -9.306362899874632e-05, -9.853852446128908e-05,
            -0.00010401346269561795, -0.00010948848007624745, -0.00011496356205126235,
            -0.00012043873771938607, -0.00012591405800388422, -0.0001313896174768847,
            -0.00013686561255793483,
        ]
        initial_y = [
            -0.7174587249755859, -1.4349095821380615, -2.1523525714874268,
            -2.8697879314422607, -3.5872151851654053, -4.3046345710754395,
            -5.022046089172363, -5.739449501037598, -6.456845760345459,
            -7.174233436584473, -7.891613960266113, -8.608985900878906,
            -9.326350212097168, -10.043707847595215, -10.761056900024414,
            -11.47839641571045, -12.19572925567627, -12.913055419921875,
            -13.630372047424316, -14.347681999206543, -15.064983367919922,
            -15.782278060913086, -16.499563217163086, -17.216840744018555,
            -17.934112548828125,
        ]
        initial = JSONData.objects.create(owner=viewer, data={
            "identifier": "plot-a46fde6c-initial-25",
            "title": "a46fde6c original component-33 samples 0–24",
            "stress": {"stress_33": initial_y},
            "total_strain": {"strain_33": initial_x},
            "units": {"Stress": "MPa", "Strain": 1},
        })
        initial_case = {
            "path": reverse("json_data_detail", args=[initial.pk]),
            "x": initial_x, "y": initial_y, "xSigns": "-", "ySigns": "-",
            "exponents": {"x": -4, "y": None},
        }
        empty = JSONData.objects.create(owner=viewer, data={"title": "No curves " * 60})
        example = settings.BASE_DIR / "example_json_files/a46fde6c.json"
        sample_path = ""
        if example.is_file():
            sample_data = json.loads(example.read_text())
            self.assertEqual(initial_x, sample_data["total_strain"]["strain_33"][:25])
            self.assertEqual(initial_y, sample_data["stress"]["stress_33"][:25])
            sample = JSONData.objects.create(owner=viewer, data=sample_data)
            sample_path = reverse("json_data_detail", args=[sample.pk])
        self.client.force_login(viewer)
        environment = dict(os.environ, PLOT_BASE_URL=self.live_server_url,
                           PLOT_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           PLOT_COOKIE_NAME=settings.SESSION_COOKIE_NAME, PLOT_CASES=json.dumps(cases),
                           PLOT_EMPTY_PATH=reverse("json_data_detail", args=[empty.pk]),
                           PLOT_SAMPLE_PATH=sample_path, PLOT_INITIAL_SAMPLE=json.dumps(initial_case))
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/mechanical-plot.cjs")],
            env=environment, capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
