import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
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
            JSONData.objects.create(owner=viewer, data=data, access_type="c")
        long_data = valid_upload_object(
            identifier="long-identifier-" * 25,
            title="A detailed simulation title with long metadata " * 15,
            phase=[{"phase_name": "Titanium with a very long descriptive phase name " * 12}],
            software="A solver with a very long uploaded descriptive name " * 14,
            global_temperature=300,
        )
        JSONData.objects.create(owner=owner, data=long_data, access_type="all")
        shared = JSONData.objects.create(owner=owner, data=valid_upload_object(identifier="shared-record",
                                        phase=[{"phase_name": "Aluminium"}]), access_type="c")
        shared.shared_users.add(viewer)
        JSONData.objects.create(owner=owner, data=valid_upload_object(identifier="hidden-private-marker"), access_type="c")
        sample_path = settings.BASE_DIR / "example_json_files" / "a46fde6c.json"
        sample_source = None
        sample_object = None
        sample_cookie = None
        if sample_path.is_file():
            sample_source = sample_path.read_bytes()
            sample_user = User.objects.create_user(username="charts-browser-sample")
            AccountProfile.objects.create(user=sample_user, getting_started_dismissed_at=timezone.now())
            sample_object = JSONData.objects.create(owner=sample_user, data=json.loads(sample_source), access_type="c")
            sample_client = Client()
            sample_client.force_login(sample_user)
            sample_cookie = sample_client.cookies[settings.SESSION_COOKIE_NAME].value
        empty_client = Client()
        empty_client.force_login(empty)
        empty_cookie = empty_client.cookies[settings.SESSION_COOKIE_NAME].value
        self.client.force_login(viewer)
        environment = dict(os.environ, CHARTS_BASE_URL=self.live_server_url,
                           CHARTS_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           CHARTS_EMPTY_SESSION=empty_cookie, CHARTS_COOKIE_NAME=settings.SESSION_COOKIE_NAME)
        if sample_cookie:
            environment.update(CHARTS_SAMPLE_SESSION=sample_cookie,
                               CHARTS_SAMPLE_DETAIL_URL=reverse("json_data_detail", args=[sample_object.pk]))
        result = subprocess.run([shutil.which("node"), str(settings.BASE_DIR / "tests/browser/charts.cjs")],
                                env=environment, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if sample_source is not None:
            self.assertEqual(sample_path.read_bytes(), sample_source)
            sample_object.refresh_from_db()
            self.assertEqual(sample_object.data, json.loads(sample_source))
        print(result.stdout)
