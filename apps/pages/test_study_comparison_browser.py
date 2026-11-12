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

from .models import AccountProfile, CollectionRelationship, JSONData, ResearchCollection
from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class StudyComparisonBrowserTests(StaticLiveServerTestCase):
    """
    Explore recorded simulation differences through the actual study workbench
    """

    server_thread_class = PlotLiveServerThread

    def test_selection_comparison_navigation_exports_and_native_controls(self):
        """
        Pin records across pages and compare them without changing research data

        Synthetic records distinguish equal, differing, missing and ambiguous
        recorded metadata while retaining the original collection relationship.
        """
        self.assertTrue(shutil.which("node"), "Study browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="study-browser-viewer")
        other = User.objects.create_user(username="study-browser-other")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        template = {
            "software": "DAMASK", "software_version": "3.0",
            "creator": "Recorded simulation researcher",
            "RVE_size": [1, 2, 3], "RVE_continuity": True,
            "discretization_type": "Structured", "discretization_count": 2744,
            "global_temperature": 298,
            "units": {"Temperature": "K", "Length": "µm", "Stress": "MPa", "Strain": "1"},
            "phase": [{
                "phase_name": "Copper", "lattice_structure": "FCC",
                "orientation": {"texture_type": "Goss", "grain_count": 343},
                "constitutive_model": {
                    "elastic_model_name": "Anisotropic Elasticity",
                    "plastic_model_name": "Crystal Plasticity",
                },
            }],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "static"}],
            "relation": ["10.1234/study-source"],
            "stress": {"equivalent_stress": [0, 10.123456789, 21]},
            "total_strain": {"equivalent_strain": [0, 0.001, 0.002]},
        }
        records = []
        for index in range(33):
            data = deepcopy(template)
            data.update(identifier=f"study-browser-{index}", title=f"Study run {index:02}")
            if index == 0:
                data["title"] += " baseline"
            elif index == 30:
                data["title"] = "=SUM(1,2) Study run 30 varied settings"
                data["software_version"] = "4.0"
                data["global_temperature"] = 323
                data["phase"][0]["orientation"]["grain_count"] = 500
            elif index == 31:
                data["title"] += " missing measurements"
                data.pop("global_temperature")
                data["phase"][0]["orientation"].pop("grain_count")
            elif index == 32:
                data["title"] += " ambiguous " + "long supplied description " * 8
                data["title"] += "<img src=x onerror=window.studyInjection=true>"
                data["Global Temperature"] = 343
            owner = other if index in (30, 32) else viewer
            record = JSONData.objects.create(owner=owner, access_type="all" if index == 30 else "c", data=data)
            if index == 32:
                record.shared_users.add(viewer)
            records.append(record)
        hidden = JSONData.objects.create(owner=other, data={
            "title": "SECRET inaccessible study record", "identifier": "SECRET-study-object",
        })
        collection = ResearchCollection.objects.create(
            owner=viewer, title="Copper simulation study",
            description="Inspect the recorded settings before following the simulation results.",
        )
        collection.members.add(*records, hidden)
        relationship = CollectionRelationship.objects.create(
            collection=collection, source=records[30], target=records[0], label="Compared with baseline",
        )
        empty = ResearchCollection.objects.create(owner=viewer, title="New simulation study")
        original_data = dict(JSONData.objects.values_list("pk", "data"))
        self.client.force_login(viewer)
        temporary = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [records[0].pk, records[30].pk],
        })
        self.assertEqual(temporary.status_code, 302)
        cases = {
            "collection": reverse("collection_detail", args=[collection.pk]),
            "empty": reverse("collection_detail", args=[empty.pk]),
            "temporary": temporary.url, "baseline": records[0].pk, "changed": records[30].pk,
            "missing": records[31].pk, "ambiguous": records[32].pk, "hidden": hidden.pk,
            "relationship": relationship.pk,
        }
        environment = dict(
            os.environ, STUDY_BASE_URL=self.live_server_url,
            STUDY_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            STUDY_COOKIE_NAME=settings.SESSION_COOKIE_NAME, STUDY_CASES=json.dumps(cases),
        )
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/study-comparison.cjs")],
            env=environment, capture_output=True, text=True, timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(dict(JSONData.objects.values_list("pk", "data")), original_data)
        relationship.refresh_from_db()
        self.assertEqual(relationship.revision, 1)
        self.assertEqual(CollectionRelationship.objects.count(), 1)
        saved = ResearchCollection.objects.get(owner=viewer, title="Saved native comparison study")
        self.assertEqual(set(saved.members.values_list("pk", flat=True)), {records[0].pk, records[30].pk})
        print(result.stdout)
