import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class BoundaryBrowserTests(StaticLiveServerTestCase):
    """
    Verify boundary diagrams in a real browser against isolated test data
    """

    def test_all_boundary_locations_and_tensor_records_on_desktop(self):
        """
        Keep geometry, quantities, record selection and original exports aligned

        The five tracked examples exercise the real detail view. Additional
        complete and mixed tensors cover signs, reciprocal values and records.
        """
        self.assertTrue(shutil.which("node"), "Node with global WebSocket is required")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file(),
                        "Chromium is required; browser checks may not be skipped")
        owner = User.objects.create_user(username="boundary-browser-owner")
        AccountProfile.objects.create(user=owner, getting_started_dismissed_at=timezone.now())
        client = Client()
        client.force_login(owner)
        examples = settings.BASE_DIR / "example_json_files/boundary_condition_examples_20261008"
        names = {
            "point": "01_point_tension_aluminium.json",
            "edge": "02_edge_compression_steel.json",
            "face": "03_face_cyclic_shear_titanium.json",
            "tensor": "04_whole_cube_tensor_copper.json",
            "whole": "04_whole_cube_force_displacement_copper.json",
        }
        data = {}
        originals = {}
        for key, name in names.items():
            path = examples / name
            originals[path] = path.read_bytes()
            data[key] = json.loads(originals[path])

        full = deepcopy(data["tensor"])
        full["title"] = "Complete tensor with independent shear components"
        magnitude = {"xx": -15, "yy": 5, "zz": -3, "xy": 2, "yx": -7,
                     "xz": -4, "zx": 6, "yz": 8, "zy": -9}
        full["mechanical_BC"][0]["applied_load"] = [
            {"magnitude": magnitude, "step": 7},
            {"magnitude": {"xx": 0, "yy": 1}, "step": 3},
            {"magnitude": magnitude, "step": 123456789012345},
            {"magnitude": magnitude},
        ]
        data["records"] = full
        elastic = deepcopy(data["tensor"])
        symmetric = {"xx": -15, "yy": 5, "zz": -3, "xy": 2, "yx": 2,
                     "xz": 0, "zx": 0, "yz": 0, "zy": 0}
        elastic["mechanical_BC"][0]["applied_load"] = [
            {"magnitude": symmetric, "step": 1},
            {"magnitude": {key: value * 2 for key, value in symmetric.items()}, "step": 2},
        ]
        data["elastic"] = elastic
        conflict = deepcopy(data["tensor"])
        conflict["phase"][0]["constitutive_model"]["elastic_parameters"]["Youngs Modulus"] = 1
        data["conflict"] = conflict

        mixed = deepcopy(full)
        mixed["title"] = "Long boundary metadata " * 20
        strain = deepcopy(full["mechanical_BC"][0])
        strain["loading_type"] = "strain"
        strain["applied_load"] = [{"magnitude": {"xx": .02, "yy": -.01, "zz": .01,
            "xy": .01, "yx": .01, "xz": 0, "zx": 0, "yz": 0, "zy": 0}, "step": 0}]
        displacement = deepcopy(data["whole"]["mechanical_BC"][0])
        displacement["loading_type"] = "displacement"
        mixed["mechanical_BC"] += [strain] + data["point"]["mechanical_BC"][:1]
        mixed["mechanical_BC"] += data["edge"]["mechanical_BC"][:1] + data["face"]["mechanical_BC"][:1]
        mixed["mechanical_BC"] += data["whole"]["mechanical_BC"] + [displacement]
        data["mixed"] = mixed
        zero = deepcopy(data["whole"])
        zero["mechanical_BC"][0]["applied_load"] = [{"magnitude": 0}, {"magnitude": 0}]
        data["zero"] = zero
        empty = deepcopy(data["whole"])
        empty["mechanical_BC"] = []
        data["empty"] = empty

        objects = {}
        pages = {}
        for key, value in data.items():
            obj = JSONData.objects.create(owner=owner, data=value)
            objects[key] = obj
            pages[key] = reverse("json_data_detail", args=[obj.pk])

        environment = os.environ.copy()
        environment["BC_BROWSER_CONFIG"] = json.dumps({
            "baseUrl": self.live_server_url,
            "session": client.cookies[settings.SESSION_COOKIE_NAME].value,
            "cookieName": settings.SESSION_COOKIE_NAME,
            "pages": pages,
        })
        result = subprocess.run([shutil.which("node"), str(settings.BASE_DIR / "tests/browser/boundary.cjs")],
                                env=environment, capture_output=True, text=True, timeout=180, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
        for key, obj in objects.items():
            self.assertEqual(client.get(reverse("json_data_export", args=[obj.pk])).json(), data[key])
            obj.refresh_from_db()
            self.assertEqual(obj.data, data[key])
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
