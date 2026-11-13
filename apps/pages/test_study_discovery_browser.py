"""
Verify native candidate discovery and linked recorded curves in desktop Chromium
"""

import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData, ResearchCollection
from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class StudyDiscoveryBrowserTests(StaticLiveServerTestCase):
    """
    Follow candidates into source-preserving recorded curve comparison
    """

    server_thread_class = PlotLiveServerThread

    def test_candidates_curves_and_native_navigation(self):
        """
        Find explicit matches and inspect complete loops without changing source data
        """
        self.assertTrue(shutil.which("node"), "Study browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="study-discovery-browser")
        other = User.objects.create_user(username="study-discovery-other")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        template = {
            "software": "DAMASK", "software_version": "3.0",
            "RVE_size": [1, 2, 3], "RVE_continuity": True,
            "discretization_type": "Structured", "discretization_count": 2744,
            "global_temperature": 298,
            "units": {"Temperature": "K", "Length": "µm", "Stress": "MPa", "Strain": "1"},
            "phase": [{"phase_name": "Copper", "lattice_structure": "FCC",
                       "orientation": {"texture_type": "Goss", "grain_count": 343},
                       "constitutive_model": {"elastic_model_name": "Anisotropic elasticity",
                                              "plastic_model_name": "Crystal plasticity"}}],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "cyclic"}],
            "stress": {"equivalent_stress": [0, 20.123456789, 38], "stress_11": [0, 30, -15, 12, 24]},
            "total_strain": {"equivalent_strain": [0, .001, .002, .003],
                             "strain_11": [0, .003, -.001, .001, .002]},
            "plastic_strain": {"equivalent_plastic_strain": [0, .0003, .0008],
                               "plastic_strain_11": [0, .0005, -.0001, .0002, .0004]},
        }
        records = {}
        collection = ResearchCollection.objects.create(owner=viewer, title="Copper temperature study")
        specifications = [("baseline", "Reference copper response", 298)]
        specifications.extend((f"variant-{index}", f"Copper temperature run {index:02}", 310 + index)
                              for index in range(26))
        specifications.extend([
            ("uncertain", "Temperature not supplied", None),
            ("excluded", "Different recorded solver", 340),
            ("mismatch", "Stress recorded in GPa", 350),
            ("missing", "Equivalent response not supplied", 360),
            ("changed", "Warmer copper response", 323),
        ])
        for key, title, temperature in specifications:
            data = deepcopy(template)
            data.update(identifier="discovery-" + key, title=title, global_temperature=temperature)
            if key == "excluded":
                data["software"] = "Another solver"
            if key == "mismatch":
                data["units"]["Stress"] = "GPa"
            if key == "missing":
                data["stress"]["equivalent_stress"] = []
            if key == "changed":
                data["stress"]["equivalent_stress"] = [0, 18.987654321, 32]
                data["stress"]["stress_11"] = [0, 27, -12, 10, 20]
            record = JSONData.objects.create(
                owner=other if key == "changed" else viewer,
                access_type="all" if key == "changed" else "c", data=data,
                size_bytes=len(json.dumps(data).encode()),
            )
            collection.members.add(record)
            records[key] = record
        hidden = JSONData.objects.create(owner=other, data={"title": "SECRET inaccessible response"})
        collection.members.add(hidden)
        original = dict(JSONData.objects.values_list("pk", "data"))
        self.client.force_login(viewer)
        temporary = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [records["baseline"].pk, records["changed"].pk],
        })
        self.assertEqual(temporary.status_code, 302)
        cases = {key: record.pk for key, record in records.items() if not key.startswith("variant-")}
        cases.update(collection=reverse("collection_detail", args=[collection.pk]), temporary=temporary.url,
                     hidden=hidden.pk)
        environment = dict(os.environ, STUDY_BASE_URL=self.live_server_url,
                           STUDY_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           STUDY_COOKIE_NAME=settings.SESSION_COOKIE_NAME, STUDY_CASES=json.dumps(cases))
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/study-discovery.cjs")],
            env=environment, capture_output=True, text=True, timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(dict(JSONData.objects.values_list("pk", "data")), original)
        self.assertEqual(collection.members.count(), len(records) + 1)
        print(result.stdout)
