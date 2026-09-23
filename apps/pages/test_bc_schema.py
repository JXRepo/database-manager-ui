import json
from copy import deepcopy

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData
from .views import _build_mechanical_bc_items, _normalize_applied_load


class MechanicalBCSchemaTests(TestCase):
    """
    Check current scalar and tensor boundary conditions on detail pages
    """

    def _tensor_data(self, loading_type="stress"):
        """
        Build a full cube condition containing two distinct tensor load steps

        Parameters
        ----------
        loading_type : str, optional
            Prescribed tensor quantity.

        Returns
        -------
        dict
            Metadata with reversed tensor keys and zero valued step metadata.
        """
        return {"mechanical_BC": [{
            "vertex_list": ["V000", "V100", "V010", "V110", "V001", "V101", "V011", "V111"],
            "constraints": ["loaded"],
            "loading_type": loading_type,
            "loading_mode": "intermittent",
            "applied_load": [
                {
                    "magnitude": {
                        "zy": 9, "zx": 8, "yx": 7, "xz": 6, "yz": 5,
                        "xy": 4, "zz": 3, "yy": 2, "xx": -1.23456789,
                    },
                    "step": 0, "duration": 5, "frequency": 0, "R": 0,
                },
                {
                    "magnitude": {"xz": 60, "yz": 50, "xy": 40, "zz": 30, "yy": 20, "xx": -10},
                    "step": 1, "duration": 10,
                },
            ],
        }]}

    def test_scalar_load_step_remains_visible_without_changing_axis_mapping(self):
        """
        Include load steps while retaining the existing scalar axis assignment
        """
        data = {"mechanical_BC": [{
            "vertex_list": ["V000"], "constraints": ["fixed", "loaded", "free"],
            "loading_type": "force", "loading_mode": "static",
            "applied_load": [{"magnitude": -4, "step": 10001}],
        }]}

        item = _build_mechanical_bc_items(data)[0]

        self.assertEqual([axis["status"] for axis in item["axes"]], ["fixed", "loaded", "free"])
        self.assertEqual(item["axes"][1]["magnitude"], -4)
        details = item["axes"][1]["load_details"]
        self.assertEqual([(detail["key"], detail["value"]) for detail in details], [("magnitude", -4), ("step", 10001)])
        self.assertEqual(details[1]["display"], "10001")

    def test_load_values_round_half_up_without_changing_stored_values(self):
        """
        Round load details to two decimals while keeping full values and step numbers
        """
        for value, expected in (
            (-40.9775297345, "-40.98"), (-9.53837730603, "-9.54"),
            (1.005, "1.01"), (-1.005, "-1.01"), (2.675, "2.68"),
            (10, "10.00"), (0, "0.00"), (-0.004, "0.00"),
        ):
            with self.subTest(value=value):
                load = {"magnitude": value, "frequency": value, "duration": value, "R": value, "step": 10001}
                original = deepcopy(load)
                normalized = _normalize_applied_load(load)
                fields = {detail["key"]: detail for detail in normalized["details"]}
                for key in ("magnitude", "frequency", "duration", "R"):
                    self.assertEqual(fields[key]["display"], expected)
                    self.assertEqual(fields[key]["value"], value)
                self.assertEqual(fields["step"]["display"], "10001")
                self.assertEqual(load, original)
        self.assertEqual(
            _normalize_applied_load({"magnitude": [1.005, -9.53837730603]})["details"][0]["display"],
            "[1.01, -9.54]",
        )

    def test_tensor_loads_preserve_all_steps_without_inventing_axis_constraints(self):
        """
        Represent prescribed tensors as full cube loads without scalar arrows
        """
        standard_vertices = self._tensor_data()["mechanical_BC"][0]["vertex_list"]
        vertex_lists = (
            standard_vertices,
            [vertex.lower() for vertex in standard_vertices],
            [f"corner-{index}" for index in range(8)],
        )
        for loading_type in ("stress", "strain"):
            for vertices in vertex_lists:
                with self.subTest(loading_type=loading_type, vertices=vertices):
                    data = self._tensor_data(loading_type)
                    data["mechanical_BC"][0]["vertex_list"] = vertices
                    original = deepcopy(data)

                    items = _build_mechanical_bc_items(data)

                    self.assertEqual(len(items), 1)
                    self.assertEqual(items[0]["target_type"], "Whole cube")
                    self.assertEqual(items[0]["axes"], [])
                    self.assertTrue(items[0]["is_tensor_load"])
                    self.assertEqual(len(items[0]["tensor_loads"]), 2)
                    for actual, expected in zip(items[0]["tensor_loads"], data["mechanical_BC"][0]["applied_load"]):
                        self.assertEqual(actual["magnitude"], expected["magnitude"])
                        self.assertEqual(actual["step"], expected["step"])
                    self.assertEqual(data, original)

    def test_tensor_magnitude_uses_schema_order_and_two_decimal_display(self):
        """
        Round displayed tensor components without changing their underlying values
        """
        load = self._tensor_data()["mechanical_BC"][0]["applied_load"][0]

        normalized = _normalize_applied_load(load)

        magnitude = normalized["details"][0]
        self.assertTrue(magnitude["display"].startswith('{"xx":'), "Tensor components should start with xx in JSON notation")
        displayed = json.loads(magnitude["display"])
        self.assertEqual(list(displayed), ["xx", "yy", "zz", "xy", "yx", "xz", "zx", "yz", "zy"])
        self.assertEqual(displayed, {**load["magnitude"], "xx": -1.23})
        self.assertIn('"yy": 2.00', magnitude["display"])
        self.assertEqual(magnitude["value"], load["magnitude"])

    def test_detail_page_shows_all_tensor_steps_and_preserves_download(self):
        """
        Render full cube tensor steps without misleading free or loaded axes
        """
        owner = User.objects.create_user(username="tensor-owner")
        self.client.force_login(owner)
        data = self._tensor_data()
        data["title"] = "Current tensor boundary conditions"
        obj = JSONData.objects.create(owner=owner, data=data)

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue("Tensor load 1" in response.content.decode(), "Missing tensor load display")
        self.assertContains(response, "Tensor load 2")
        self.assertContains(response, 'class="bc-load-key">step</span>:', count=2)
        self.assertContains(response, "<th>Loading type / mode</th>", html=True)
        self.assertContains(response, "&quot;xx&quot;: -1.23,")
        self.assertContains(response, "-1.23456789")
        self.assertNotContains(response, "X: loaded")
        self.assertNotContains(response, "Y: free")
        self.assertNotContains(response, "Z: free")
        exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(exported.json(), data)
        obj.refresh_from_db()
        self.assertEqual(obj.data, data)
