import os
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.utils import timezone

from apps.pages.models import AccountProfile, JSONData
from apps.pages.upload_test_data import valid_upload_object


@skipUnless(shutil.which("node") and Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file(),
            "Charts browser checks require Node and Chromium")
@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class ChartsBrowserTests(StaticLiveServerTestCase):
    """
    Exercise real Charts navigation and desktop layout against isolated SQLite
    """

    def test_desktop_statistics_navigation_and_progressive_enhancement(self):
        """
        Chart controls and drillthrough remain usable with long and empty data
        """
        viewer = User.objects.create_user(username="charts-browser-viewer")
        owner = User.objects.create_user(username="charts-browser-owner")
        empty = User.objects.create_user(username="charts-browser-empty")
        for user in (viewer, empty):
            AccountProfile.objects.create(user=user, getting_started_dismissed_at=timezone.now())
        for index in range(24):
            phase = ("Copper", "Nickel", "Steel")[index % 3]
            data = valid_upload_object(
                identifier=f"charts-browser-{index}", title=f"{phase} simulation {index + 1}",
                software=f"Software {index % 12 + 1}", global_temperature=273 + index * 25,
                discretization_count=(index + 1) * 1024,
                phase=[{"phase_name": phase,
                        "constitutive_model": {"elastic_model_name": "Anisotropic elasticity",
                                               "plastic_model_name": "Crystal plasticity"},
                        "orientation": {"grain_count": (index + 1) * 10, "texture_type": "Goss"}}],
                mechanical_BC=[{"loading_type": "force", "loading_mode": "static" if index % 2 else "cyclic"}],
                plastic_strain={"equivalent_plastic_strain": [0, .005]} if index % 2 else {},
            )
            if index == 23:
                data["stress"]["equivalent_stress"] = list(range(12000))
                data["total_strain"]["equivalent_strain"] = [value / 1000 for value in range(12002)]
            if index == 0:
                data["stress"]["stress_33"] = [0, -60, -100]
                data["total_strain"]["strain_33"] = [0, -.005, -.015]
            JSONData.objects.create(owner=viewer, data=data, access_type="c")
        long_data = valid_upload_object(
            identifier="long-identifier-" * 25,
            title="A detailed simulation title with long metadata " * 15,
            phase=[{"phase_name": "Titanium with a very long descriptive phase name " * 12}],
            software="A solver with a very long uploaded descriptive name " * 14,
        )
        JSONData.objects.create(owner=owner, data=long_data, access_type="all")
        shared = JSONData.objects.create(owner=owner, data=valid_upload_object(identifier="shared-record",
                                        phase=[{"phase_name": "Aluminium"}]), access_type="c")
        shared.shared_users.add(viewer)
        JSONData.objects.create(owner=owner, data=valid_upload_object(identifier="hidden-private-marker"), access_type="c")
        empty_client = Client()
        empty_client.force_login(empty)
        empty_cookie = empty_client.cookies[settings.SESSION_COOKIE_NAME].value
        self.client.force_login(viewer)
        environment = dict(os.environ, CHARTS_BASE_URL=self.live_server_url,
                           CHARTS_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           CHARTS_EMPTY_SESSION=empty_cookie, CHARTS_COOKIE_NAME=settings.SESSION_COOKIE_NAME)
        result = subprocess.run([shutil.which("node"), str(settings.BASE_DIR / "tests/browser/charts.cjs")],
                                env=environment, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
