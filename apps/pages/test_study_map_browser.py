"""
Exercise the parameter map and explicit recorded settings in desktop Chromium.
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
class StudyMapBrowserTests(StaticLiveServerTestCase):
    """
    Verify a native map, pinning, parameter inspection and source return workflow.
    """

    server_thread_class = PlotLiveServerThread

    def test_parameter_map_and_explicit_inspection(self):
        """
        Follow supplied parameter pairs into detailed settings and recorded curves.

        Synthetic fixtures include distinct units, incomplete values and a hidden
        member so the rendered workflow checks both coverage and authorization.
        """
        self.assertTrue(shutil.which("node"), "Study browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="study-map-browser")
        other = User.objects.create_user(username="study-map-other")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        collection = ResearchCollection.objects.create(owner=viewer, title="Copper parameter coverage")
        empty_collection = ResearchCollection.objects.create(owner=viewer, title="New parameter study")
        template = {
            "software": "DAMASK", "software_version": "3.0",
            "global_temperature": 298, "discretization_count": 100,
            "units": {"Temperature": "K", "Stress": "MPa", "Strain": "1"},
            "phase": [{
                "phase_name": "Copper", "lattice_structure": "FCC",
                "constitutive_model": {
                    "elastic_model_name": "Anisotropic elasticity",
                    "elastic_parameters": {"C11": "210.000000000000000001", "C12": 0},
                    "plastic_parameters": {"active": False},
                    "units": {"C11": "GPa"},
                },
            }],
            "mechanical_BC": [{
                "loading_type": "stress", "loading_mode": "cyclic",
                "stress_tensor": {"stress_11": [0, 10, -3]}, "recorded_step": 0,
            }],
            "stress": {"equivalent_stress": [0, 20.123456789, 38]},
            "total_strain": {"equivalent_strain": [0, .001, .002, .003]},
        }
        specifications = [
            ("baseline", "Reference copper response", 298, 100),
            ("duplicate", "Second record at the same settings", 298, 100),
            ("changed", "Changed model and loading", 323, 200),
        ]
        for index in range(9):
            specifications.append((f"variant-{index}", f"Coverage run {index}", 330 + index, 300 + index))
        specifications.extend([
            ("celsius", "Temperature supplied in Celsius", 25, 100),
            ("missing", "Temperature not supplied", None, 100),
            ("invalid", "Invalid temperature", "warm", 100),
            ("ambiguous", "Conflicting temperature fields", 298, 100),
            ("unsupported", "Unknown temperature unit", 298, 100),
        ])
        records = {}
        for key, title, temperature, count in specifications:
            data = deepcopy(template)
            data.update(identifier="map-" + key, title=title,
                        global_temperature=temperature, discretization_count=count)
            if key == "changed":
                data["phase"][0]["constitutive_model"]["elastic_parameters"]["C11"] = "220.000000000000000002"
                data["mechanical_BC"][0]["stress_tensor"]["stress_11"] = [0, 12, -4]
            elif key == "celsius":
                data["units"]["Temperature"] = "°C"
            elif key == "ambiguous":
                data["Global Temperature"] = 999
            elif key == "unsupported":
                data["units"]["Temperature"] = "custom temperature"
            record = JSONData.objects.create(
                owner=other if key == "changed" else viewer,
                access_type="all" if key == "changed" else "c",
                data=data, size_bytes=len(json.dumps(data).encode()),
            )
            collection.members.add(record)
            records[key] = record
        hidden = JSONData.objects.create(owner=other, data={"title": "SECRET inaccessible response"})
        collection.members.add(hidden)
        preparing_collection = ResearchCollection.objects.create(owner=viewer, title="Preparing a parameter study")
        preparing_collection.members.add(*records.values())
        for index in range(10):
            data = deepcopy(template)
            data.update(identifier=f"preparing-{index}", title=f"Preparing record {index}")
            record = JSONData.objects.create(owner=viewer, data=data, size_bytes=len(json.dumps(data).encode()))
            preparing_collection.members.add(record)
        for record in preparing_collection.members.all():
            summary = record.collection_summary
            summary["summary_version"] = 2
            summary.pop("parameter_map", None)
            JSONData.objects.filter(pk=record.pk).update(collection_summary=summary)
        original = dict(JSONData.objects.values_list("pk", "data"))
        self.client.force_login(viewer)
        temporary = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [records["baseline"].pk, records["changed"].pk],
        })
        self.assertEqual(temporary.status_code, 302)
        cases = {}
        for key, record in records.items():
            if not key.startswith("variant-"):
                cases[key] = record.pk
        cases.update(
            collection=reverse("collection_detail", args=[collection.pk]),
            empty=reverse("collection_detail", args=[empty_collection.pk]),
            preparing=reverse("collection_detail", args=[preparing_collection.pk]),
            temporary=temporary.url, total=len(records), hidden=hidden.pk,
        )
        environment = dict(
            os.environ, STUDY_BASE_URL=self.live_server_url,
            STUDY_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            STUDY_COOKIE_NAME=settings.SESSION_COOKIE_NAME, STUDY_CASES=json.dumps(cases),
        )
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/study-map.cjs")],
            env=environment, capture_output=True, text=True, timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(dict(JSONData.objects.values_list("pk", "data")), original)
        self.assertEqual(collection.members.count(), len(records) + 1)
        print(result.stdout)
