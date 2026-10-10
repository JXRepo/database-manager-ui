import json
import re
from copy import deepcopy

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData
from .views import (
    _build_mechanical_bc_items,
    _group_mechanical_bc_items,
    _normalize_applied_load,
)


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
        self.assertContains(response, "<th>Loading Type / Mode</th>", html=True)
        self.assertContains(response, "&quot;xx&quot;: -1.23,")
        self.assertContains(response, "-1.23456789")
        self.assertNotContains(response, "X: loaded")
        self.assertNotContains(response, "Y: free")
        self.assertNotContains(response, "Z: free")
        self.assertContains(response, "Entire cube", count=1)
        exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(exported.json(), data)
        obj.refresh_from_db()
        self.assertEqual(obj.data, data)

    def test_detail_groups_targets_without_changing_tensor_selection_or_data(self):
        """
        Group mixed targets while keeping tensor buttons linked to their source

        The table may reorder target categories, but cube selection and exports
        must retain the original conditions and load entries.
        """
        owner = User.objects.create_user(username="grouped-bc-owner")
        self.client.force_login(owner)
        data = {"mechanical_BC": [
            self._tensor_data()["mechanical_BC"][0],
            {"vertex_list": ["V000", "V010", "V001", "V011"],
             "constraints": ["fixed", "fixed", "fixed"]},
            {"vertex_list": ["V111"], "constraints": ["loaded", "free", "free"],
             "loading_type": "force", "applied_load": [{"magnitude": 32}]},
            {"vertex_list": ["V010", "V110"], "constraints": ["free", "loaded", "free"],
             "loading_type": "force", "applied_load": [{"magnitude": -172.8}]},
            {"vertex_list": ["V001", "V101", "V011", "V111"],
             "constraints": ["free", "free", "loaded"], "loading_type": "force",
             "applied_load": [{"magnitude": 405}]},
            self._tensor_data("strain")["mechanical_BC"][0],
            {"vertex_list": ["V100"], "constraints": ["fixed", "free", "free"]},
        ]}
        original = deepcopy(data)
        obj = JSONData.objects.create(owner=owner, data=data)

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        html = response.content.decode()
        groups = re.findall(r'<tbody data-bc-target-type="([^"]+)">(.*?)</tbody>', html, re.S)

        self.assertEqual([kind for kind, _ in groups], ["Point", "Edge", "Face", "Whole cube"])
        self.assertContains(response, 'class="bc-table-group"', count=4)
        self.assertContains(response, 'class="bc-table-frame"', count=4)
        self.assertNotContains(response, 'class="bc-group-heading"')
        self.assertEqual(
            re.findall(r'<span class="bc-target-vertex">([^<]+)</span>', groups[0][1]),
            ["V111", "V100"],
        )
        self.assertEqual(
            re.findall(r'<span class="bc-target-vertex"[^>]*>([^<]+)</span>', groups[2][1]),
            ["V000", "V010", "V001", "V011", "V001", "V101", "V011", "V111"],
        )
        self.assertEqual(
            re.findall(r'data-bc-show-tensor="(\d+)".*?data-bc-load-index="(\d+)"', groups[3][1]),
            [("0", "0"), ("0", "1"), ("5", "0"), ("5", "1")],
        )
        script = re.search(r'<script id="mechanical-bc-data"[^>]*>(.*?)</script>', html, re.S)
        items = json.loads(script.group(1))
        self.assertEqual([item["target_type"] for item in items],
                         ["Whole cube", "Face", "Point", "Edge", "Face", "Whole cube", "Point"])
        self.assertEqual([load["step"] for load in items[5]["tensor_loads"]], [0, 1])
        self.assertEqual(self.client.get(reverse("json_data_export", args=[obj.pk])).json(), original)
        obj.refresh_from_db()
        self.assertEqual(obj.data, original)

    def test_face_connections_follow_all_six_surfaces_without_reordering_vertices(self):
        """
        Keep real face connections correct for different supplied vertex orders

        Each displayed neighbor must be a cube edge. Display positions must not
        change the vertex list passed to the viewer or stored in the data.
        """
        faces = (
            ["V000", "V010", "V001", "V011"],
            ["V100", "V110", "V101", "V111"],
            ["V000", "V100", "V001", "V101"],
            ["V010", "V110", "V011", "V111"],
            ["V000", "V100", "V010", "V110"],
            ["V001", "V101", "V011", "V111"],
        )
        for face in faces:
            orders = (face, [face[3], face[0], face[2], face[1]], [v.lower() for v in face])
            for vertices in orders:
                with self.subTest(vertices=vertices):
                    data = {"mechanical_BC": [{"vertex_list": vertices}]}
                    original = deepcopy(data)
                    items = _build_mechanical_bc_items(data)
                    group = next(g for g in _group_mechanical_bc_items(items) if g["target_type"] == "Face")
                    row = group["rows"][0]
                    layout = row["target_layout"]
                    self.assertEqual(layout["kind"], "face")
                    self.assertIs(row["item"], items[0])
                    self.assertEqual([v["name"] for v in layout["vertices"]], vertices)
                    corners = {(v["row"], v["column"]): v["name"] for v in layout["vertices"]}
                    self.assertEqual(set(corners), {(1, 1), (1, 3), (3, 1), (3, 3)})
                    for start, end in (
                        ((1, 1), (1, 3)), ((1, 3), (3, 3)),
                        ((3, 3), (3, 1)), ((3, 1), (1, 1)),
                    ):
                        self.assertEqual(sum(a != b for a, b in zip(corners[start], corners[end])), 1)
                    self.assertEqual(items[0]["vertices"], vertices)
                    self.assertEqual(data, original)

    def test_connections_do_not_invent_cube_edges_or_external_faces(self):
        """
        Leave diagonal, unknown and repeated vertex sets without drawn connections

        The existing target classification is retained for these records while
        their table display avoids suggesting an unsupported cube surface.
        """
        for vertices in (
            ["V000", "V111"],
            ["V000", "V001", "V110", "V111"],
            ["V000", "V110", "V101", "V011"],
            ["corner-left", "corner-right"],
            ["corner-a", "corner-b", "corner-c", "corner-d"],
            ["V000", "V100", "V000"],
            ["V000", "V100", "V010", "V110", "V000"],
        ):
            with self.subTest(vertices=vertices):
                items = _build_mechanical_bc_items({"mechanical_BC": [{"vertex_list": vertices}]})
                rows = [row for group in _group_mechanical_bc_items(items) for row in group["rows"]]
                row = next(row for row in rows if row["source_index"] == 0)
                self.assertEqual(row["target_layout"], {})
                self.assertEqual(row["item"]["vertices"], vertices)

    def test_edge_detail_groups_unused_points_and_omits_empty_target_groups(self):
        """
        Keep free vertices visible together without adding empty table sections
        """
        owner = User.objects.create_user(username="edge-group-owner")
        self.client.force_login(owner)
        obj = JSONData.objects.create(owner=owner, data={"mechanical_BC": [
            {"vertex_list": ["V010", "V110"], "constraints": ["free", "loaded", "free"],
             "loading_type": "force", "applied_load": [{"magnitude": -172.8}]},
            {"vertex_list": ["V000", "V100", "V001", "V101"],
             "constraints": ["fixed", "fixed", "fixed"]},
        ]})

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        groups = re.findall(r'<tbody data-bc-target-type="([^"]+)">(.*?)</tbody>',
                            response.content.decode(), re.S)

        self.assertEqual([kind for kind, _ in groups], ["Point", "Edge", "Face"])
        self.assertEqual(
            re.findall(r'<span class="bc-target-vertex">([^<]+)</span>', groups[0][1]),
            ["V011", "V111"],
        )
