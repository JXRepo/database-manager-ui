import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData
from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class RelationshipBrowserTests(StaticLiveServerTestCase):
    """
    Exercise relationship navigation and long content in desktop Chromium
    """

    server_thread_class = PlotLiveServerThread

    def test_relationship_graph_interaction_and_native_fallback(self):
        """
        Navigate the independent workspace and retain access without scripts
        """
        self.assertTrue(shutil.which("node"), "Relationship browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="relationship-browser-viewer")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        sample = JSONData.objects.create(owner=viewer, data={
            "identifier": "relationship-demo", "title": "Two phase steel under uniaxial loading",
            "creator": ["Alice Example", "Bob Example"], "software": "DAMASK",
            "software_version": "3.0", "phase": [
                {"phase_name": "Ferrite", "phase_id": 0, "constitutive_model": {
                    "elastic_model_name": "Cubic elasticity",
                    "elastic_parameters": {"C11": 233000, "units": "MPa"},
                    "plastic_model_name": "Phenomenological crystal plasticity",
                }},
                {"phase_name": "Martensite", "phase_id": 1, "constitutive_model": {
                    "elastic_model_name": "Isotropic elasticity",
                }},
            ],
            "stress": {"stress_11": [0, 80, 160]},
            "total_strain": {"strain_11": [0, .01, .02, .03]},
            "mechanical_BC": [{
                "vertex_list": ["V000"], "constraints": ["fixed", "loaded", "free"],
                "loading_type": "force", "loading_mode": "static",
                "applied_load": [{"magnitude": -4, "step": 10001}],
            }],
            "units": {"Stress": "MPa", "Strain": "1"},
        })
        long_name = "WWW" * 100 + " <script>window.graphInjection = true</script>"
        phases = []
        for index in range(12):
            phases.append({"phase_name": f"Phase {index}: {long_name}", "constitutive_model": {
                "elastic_model_name": f"Elastic model {index}: {long_name}",
            }})
        long_record = JSONData.objects.create(owner=viewer, data={
            "title": "Long names and many phases " * 30, "creator": long_name,
            "phase": phases,
        })
        empty = JSONData.objects.create(owner=viewer, data={"title": "No related metadata"})
        large_record = JSONData.objects.create(owner=viewer, data={
            "title": "Eighty distinct phase entries", "phase": [
                {"phase_name": f"Phase {index}", "constitutive_model": {
                    "elastic_model_name": f"Elastic model {index}",
                }} for index in range(80)
            ],
        })
        examples = []
        example_directory = settings.BASE_DIR / "example_json_files/boundary_condition_examples_20261008"
        for path in sorted(example_directory.glob("*.json")):
            record = JSONData.objects.create(owner=viewer, data=json.loads(path.read_text()))
            examples.append({"name": path.stem, "url": f"{reverse('graph')}?object={record.pk}"})
        for index in range(max(0, 105 - len(examples))):
            JSONData.objects.create(owner=viewer, data={
                "title": f"Reference simulation {index}", "identifier": f"reference-{index}",
            })
        cases = {"sample": f"{reverse('graph')}?object={sample.pk}",
                 "long": f"{reverse('graph')}?object={long_record.pk}",
                 "empty": f"{reverse('graph')}?object={empty.pk}",
                 "large": f"{reverse('graph')}?object={large_record.pk}",
                 "detail": reverse("json_data_detail", args=[sample.pk]),
                 "examples": examples,
                 "picker": reverse("graph")}
        self.client.force_login(viewer)
        environment = dict(os.environ, RELATIONSHIP_BASE_URL=self.live_server_url,
                           RELATIONSHIP_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           RELATIONSHIP_COOKIE_NAME=settings.SESSION_COOKIE_NAME,
                           RELATIONSHIP_CASES=json.dumps(cases))
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/relationships.cjs")],
            env=environment, capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
