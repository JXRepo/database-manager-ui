import json
import re
from copy import deepcopy

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData
from .views import _build_detail_rows


class DetailMetadataTests(TestCase):
    """
    Verify metadata ordering without losing uploaded information or access rules
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create the owner and another signed in user for detail requests
        """
        cls.owner = User.objects.create_user(username="metadata-owner")
        cls.viewer = User.objects.create_user(username="metadata-viewer")

    def setUp(self):
        """
        Open detail pages as the data owner by default
        """
        self.client.force_login(self.owner)

    def _detail(self, data):
        """
        Store an object and request its rendered detail page

        Parameters
        ----------
        data : dict
            Metadata to store unchanged.

        Returns
        -------
        tuple
            Stored object and successful detail response.
        """
        obj = JSONData.objects.create(owner=self.owner, data=data)
        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        self.assertEqual(response.status_code, 200)
        return obj, response

    def test_mandatory_order_survives_reversed_and_database_key_order(self):
        """
        Show visible mandatory fields before other metadata without a wrapper group
        """
        expected = [
            "title", "creator", "creator_affiliation", "date", "shared_with",
            "rights", "rights_holder", "software", "software_version", "system",
            "system_version", "processor_specifications", "input_path", "results_path",
            "RVE_size", "RVE_continuity", "discretization_type",
            "discretization_unit_size", "discretization_count", "phase", "units",
        ]
        optional = ["identifier", "creator_ORCID", "CPU_specifications", "$schema"]
        hidden = ["mechanical_BC", "stress", "total_strain"]
        orders = (
            list(reversed(expected + optional + hidden)),
            sorted(expected + optional + hidden, key=lambda key: (len(key), key)),
            list(reversed(expected)),
        )

        for keys in orders:
            with self.subTest(keys=keys):
                data = {key: f"Value for {key}" for key in keys}
                obj, response = self._detail(data)
                rows = response.context["detail_rows"]
                displayed = [row["label"] for row in rows]
                additional = [key for key in keys if key in optional]

                self.assertEqual(displayed, expected + additional)
                html = response.content.decode()
                positions = [html.index(f">{key}</") for key in expected]
                self.assertEqual(positions, sorted(positions))
                obj.refresh_from_db()
                self.assertEqual(json.dumps(obj.data), json.dumps(data))

    def test_extra_fields_follow_mandatory_fields_and_escape_uploads(self):
        """
        Show extra top level fields directly and escape their labels and values
        """
        uploaded_label = '<img src=x onerror="alert(1)">'
        uploaded_value = '<script>alert("metadata")</script>'
        _, response = self._detail({
            uploaded_label: uploaded_value,
            "$schema": "https://example.test/metadata.schema.json",
            "custom_flag": False,
            "title": "An object with additional metadata",
            "identifier": "additional-fields",
        })
        rows = response.context["detail_rows"]
        self.assertEqual(
            [row["label"] for row in rows[21:]],
            [uploaded_label, "$schema", "custom_flag", "identifier"],
        )
        self.assertNotIn("Additional metadata", [row["label"] for row in rows])
        self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
        self.assertContains(response, "&lt;script&gt;alert(&quot;metadata&quot;)&lt;/script&gt;")
        self.assertNotContains(response, uploaded_label)
        self.assertNotContains(response, uploaded_value)
        self.assertContains(response, "https://example.test/metadata.schema.json")

    def test_optional_fields_are_shown_only_when_supplied(self):
        """
        Keep supplied flat metadata separate without adding absent optional fields
        """
        _, response = self._detail({
            "creator_ORCID": ["0000-0002-1451-2715"],
            "identifier": "optional-fields",
            "CPU_specifications": "Legacy CPU description",
            "description": "Optional simulation description",
            "creator_institute": "Institute of Materials",
            "creator_group": "Simulation Group",
            "title": "Optional metadata",
        })
        rows = response.context["detail_rows"]
        labels = [row["label"] for row in rows]
        optional_labels = [row["label"] for row in rows[21:]]

        self.assertEqual(
            optional_labels,
            [
                "creator_ORCID", "identifier", "CPU_specifications", "description",
                "creator_institute", "creator_group",
            ],
        )
        self.assertTrue(all(row["type"] != "group" for row in rows))
        for key in ("thermal_BC", "user_extra_information", "system_extra_information"):
            self.assertNotIn(key, labels + optional_labels)
        self.assertNotIn("Additional metadata", labels)
        self.assertContains(response, "0000-0002-1451-2715")
        self.assertContains(response, "Legacy CPU description")

    def test_nested_schema_fields_precede_extras_without_reordering_array_items(self):
        """
        Sort each phase by its schema while preserving phase and value sequences
        """
        data = {
            "phase": [
                {
                    "custom_note": "First phase note",
                    "orientation": {
                        "custom_orientation": "Extra orientation data",
                        "grain_count": 8,
                        "euler_angles": [30, 20, 10],
                    },
                    "volume_fraction": 0.7,
                    "phase_id": 2,
                    "phase_name": "First phase",
                    "constitutive_model": {
                        "plastic_model_name": "Model P",
                        "elastic_model_name": "Model E",
                    },
                },
                {
                    "custom_note": "Second phase note",
                    "orientation": {"grain_count": 13, "euler_angles": [60, 50, 40]},
                    "phase_id": 1,
                    "phase_name": "Second phase",
                },
            ],
        }
        original = deepcopy(data)
        rows = _build_detail_rows(data)

        self.assertEqual(
            [row["label"] for row in rows],
            [
                "phase / Item 1 / phase_name",
                "phase / Item 1 / constitutive_model / plastic_model_name",
                "phase / Item 1 / constitutive_model / elastic_model_name",
                "phase / Item 1 / custom_note",
                "phase / Item 1 / orientation / euler_angles",
                "phase / Item 1 / orientation / grain_count",
                "phase / Item 1 / orientation / custom_orientation",
                "phase / Item 1 / volume_fraction", "phase / Item 1 / phase_id",
                "phase / Item 2 / phase_name", "phase / Item 2 / custom_note",
                "phase / Item 2 / orientation / euler_angles",
                "phase / Item 2 / orientation / grain_count",
                "phase / Item 2 / phase_id",
            ],
        )
        self.assertEqual(
            [row["value"] for row in rows],
            [
                "First phase", "Model P", "Model E", "First phase note",
                [30, 20, 10], 8, "Extra orientation data", 0.7, 2,
                "Second phase", "Second phase note", [60, 50, 40], 13, 1,
            ],
        )
        self.assertEqual(json.dumps(data), json.dumps(original))

        _, response = self._detail(data)
        phase = next(row for row in response.context["detail_rows"] if row["label"] == "phase")
        self.assertEqual([item["label"] for item in phase["children"]], ["Item 1", "Item 2"])
        for item, name, grain_count in zip(
            phase["children"], ("First phase", "Second phase"), (8, 13),
        ):
            with self.subTest(phase=name):
                fields = {row["label"]: row for row in item["children"]}
                self.assertEqual(fields["phase_name"]["value"], name)
                orientation = {
                    row["label"]: row for row in fields["orientation"]["children"]
                }
                self.assertEqual(orientation["grain_count"]["value"], grain_count)

    def test_literal_extra_keys_remain_distinct_from_nested_schema_paths(self):
        """
        Keep punctuation in uploaded keys without treating it as a path separator
        """
        _, response = self._detail({
            "identifier": "literal-extra-keys",
            "title": "Literal metadata keys",
            "phase.note": "A literal dotted field",
            "title / explanation": "A literal slash field",
            "units[custom]": "A literal bracket field",
            "a.b": "A literal nested-looking field",
            "a": {"b": "An actual nested value", "note": "Nested group note"},
        })
        fields = {row["label"]: row for row in response.context["detail_rows"][21:]}
        self.assertEqual(
            list(fields),
            ["identifier", "phase.note", "title / explanation", "units[custom]", "a.b", "a"],
        )
        self.assertEqual(fields["a.b"]["value"], "A literal nested-looking field")
        nested = {row["label"]: row for row in fields["a"]["children"]}
        self.assertEqual(nested["b"]["value"], "An actual nested value")
        self.assertContains(response, "phase.note")
        self.assertContains(response, "title / explanation")
        self.assertContains(response, "units[custom]")

    def test_empty_legacy_object_does_not_invent_additional_metadata(self):
        """
        Keep required placeholders for empty old records without a phantom group
        """
        _, response = self._detail({})
        rows = response.context["detail_rows"]

        self.assertTrue(rows)
        self.assertEqual(len(rows), 21)
        self.assertTrue(all(row["type"] == "empty" for row in rows))
        self.assertNotIn("Additional metadata", [row["label"] for row in rows])

    def test_nested_legacy_order_and_top_level_cpu_preserve_original_names(self):
        """
        Keep optional nested fields and legacy spellings in their supplied order
        """
        data = {
            "phase": [{
                "volume_fraction": 1,
                "phase_identifier": "Copper",
                "phase_id": 1,
                "phase_name": "Copper phase",
            }],
            "origin": [{
                "Results Path": "outputs",
                "Input Path": "inputs",
                "system Version": "22.04",
                "system": "Linux",
                "software Version": "3.0",
                "software": "DAMASK",
            }],
            "input_path": "current-inputs",
            "CPU_specifications": "Legacy CPU",
            "processor_specifications": "Current CPU",
            "system_version": "24.04",
        }
        rows = _build_detail_rows(data)
        labels = [row["label"] for row in rows]

        self.assertEqual(
            [label for label in labels if label.startswith("origin / ")],
            [
                "origin / Results Path", "origin / Input Path", "origin / system Version",
                "origin / system", "origin / software Version", "origin / software",
            ],
        )
        self.assertEqual(
            [label for label in labels if label.startswith("phase / ")],
            [
                "phase / phase_name", "phase / volume_fraction",
                "phase / phase_identifier", "phase / phase_id",
            ],
        )
        _, response = self._detail(data)
        displayed = response.context["detail_rows"]
        main_fields = {row["label"]: row for row in displayed[:21]}
        optional_fields = {row["label"]: row for row in displayed[21:]}
        self.assertNotIn("CPU_specifications", main_fields)
        self.assertEqual(main_fields["processor_specifications"]["value"], "Current CPU")
        self.assertEqual(optional_fields["CPU_specifications"]["value"], "Legacy CPU")
        self.assertIn("origin", optional_fields)

    def test_visualized_fields_are_hidden_only_in_metadata_and_remain_in_export(self):
        """
        Hide duplicate mechanical metadata while keeping plots and original export
        """
        data = {
            "identifier": "raw-mechanical-fields",
            "title": "Mechanical details",
            "mechanical_BC": [{
                "boundary_note": "Boundary condition provenance",
                "vertex_list": ["V000"],
                "constraints": ["fixed", "free", "free"],
                "loading_type": "force",
                "loading_mode": "static",
            }],
            "stress": {"stress_note": "Measured stress note", "stress_11": [0, 10]},
            "total_strain": {"strain_note": "Total strain note", "strain_11": [0, 0.1]},
            "plastic_strain": {
                "plastic_note": "Plastic strain note", "plastic_strain_11": [0, 0.01],
            },
            "units": {"Stress": "MPa", "Strain": 1},
        }
        obj, response = self._detail(data)
        by_label = {row["label"]: row for row in response.context["detail_rows"]}

        for key in ("mechanical_BC", "stress", "total_strain"):
            with self.subTest(field=key):
                self.assertNotIn(key, by_label)
        self.assertEqual(by_label["plastic_strain"]["type"], "group")
        for note in (
            "Boundary condition provenance", "Measured stress note",
            "Total strain note",
        ):
            self.assertNotContains(response, note)
        self.assertContains(response, "Plastic strain note")
        variables = {item["key"]: item for item in response.context["plot_variables"]}
        self.assertEqual(variables["stress.stress_11"]["values"], [0, 10])
        self.assertEqual(variables["total_strain.strain_11"]["values"], [0, 0.1])
        self.assertEqual(variables["plastic_strain.plastic_strain_11"]["values"], [0, 0.01])
        self.assertTrue(response.context["mechanical_bc_items"])
        exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(exported.json(), data)

    def test_extra_metadata_keeps_empty_and_mixed_values(self):
        """
        Retain uploaded empty containers, nulls, and mixed arrays as direct fields
        """
        _, response = self._detail({
            "identifier": "empty-extra-values",
            "title": "Extra value types",
            "empty_object": {},
            "empty_list": [],
            "null_value": None,
            "mixed_values": [1, "two", False],
        })
        by_label = {row["label"]: row for row in response.context["detail_rows"]}
        self.assertEqual(json.loads(by_label["empty_object"]["json_value"]), {})
        self.assertEqual(json.loads(by_label["empty_list"]["json_value"]), [])
        self.assertEqual(by_label["null_value"]["type"], "empty")
        self.assertEqual(json.loads(by_label["mixed_values"]["json_value"]), [1, "two", False])

    def test_single_child_objects_stay_collapsed_and_flat_fields_stay_separate(self):
        """
        Reflect real object boundaries even when an object contains one field
        """
        _, response = self._detail({
            "title": "Object boundaries",
            "shared_with": [{"access_type": "all"}],
            "creator": ["Example Creator"],
            "creator_affiliation": ["Example University"],
            "creator_institute": ["Example Institute"],
            "creator_group": ["Example Group"],
            "custom_object": {"child": {"value": 7}},
            "custom_objects": [{"value": "One object"}],
        })
        fields = {row["label"]: row for row in response.context["detail_rows"]}

        for name in ("shared_with", "custom_object", "custom_objects"):
            with self.subTest(group=name):
                self.assertEqual(fields[name]["type"], "group")
                self.assertEqual(len(fields[name]["children"]), 1)
        child = fields["custom_object"]["children"][0]
        self.assertEqual(child["label"], "child")
        self.assertEqual(child["type"], "group")
        self.assertEqual(child["children"][0]["value"], 7)
        for name in ("creator", "creator_affiliation", "creator_institute", "creator_group"):
            self.assertEqual(fields[name]["type"], "string_list")
        self.assertNotRegex(response.content.decode(), r'<details\b[^>]*\bopen\b')

    def test_conditional_required_fields_lead_shared_and_thermal_groups(self):
        """
        Prioritize conditional requirements only when the supplied condition applies
        """
        for access_type in ("all", "c", "u", "g"):
            with self.subTest(access_type=access_type):
                _, response = self._detail({
                    "shared_with": [{
                        "username": "Example",
                        "access_list": ["team"],
                        "note": "Sharing note",
                        "access_type": access_type,
                    }],
                })
                shared = next(
                    row for row in response.context["detail_rows"]
                    if row["label"] == "shared_with"
                )
                expected = ["access_type", "username", "access_list", "note"]
                if access_type in {"u", "g"}:
                    expected = ["access_type", "access_list", "username", "note"]
                self.assertEqual([row["label"] for row in shared["children"]], expected)

        for constraint in ("fixed", "loaded"):
            with self.subTest(constraint=constraint):
                _, response = self._detail({
                    "thermal_BC": [{
                        "note": "Thermal note",
                        "applied_load": [10, 20],
                        "loading_mode": "static",
                        "constraints": [constraint],
                        "vertex_list": ["V000"],
                    }],
                })
                thermal = next(
                    row for row in response.context["detail_rows"]
                    if row["label"] == "thermal_BC"
                )
                expected = ["vertex_list", "constraints", "note", "applied_load", "loading_mode"]
                if constraint == "loaded":
                    expected = ["vertex_list", "constraints", "loading_mode", "applied_load", "note"]
                self.assertEqual([row["label"] for row in thermal["children"]], expected)

    def test_nested_required_order_does_not_add_missing_optional_fields(self):
        """
        Order orientation and Euler requirements without generating absent siblings
        """
        _, response = self._detail({
            "phase": [{
                "orientation": {
                    "note": "Orientation note",
                    "texture_type": "random",
                    "grain_count": 8,
                    "euler_angles": {"note": "Euler note", "Phi2": 30, "Phi": 20, "Phi1": 10},
                },
                "phase_name": "Copper",
            }],
        })
        phase = next(row for row in response.context["detail_rows"] if row["label"] == "phase")
        self.assertEqual([row["label"] for row in phase["children"]], ["phase_name", "orientation"])
        orientation = phase["children"][1]
        self.assertEqual(
            [row["label"] for row in orientation["children"]],
            ["euler_angles", "grain_count", "texture_type", "note"],
        )
        angles = orientation["children"][0]
        self.assertEqual(
            [(row["label"], row["value"]) for row in angles["children"]],
            [("Phi1", 10), ("Phi", 20), ("Phi2", 30), ("note", "Euler note")],
        )

    def test_microstructure_groups_prioritize_their_required_fields(self):
        """
        Keep microstructure requirements ahead of optional grain and voxel details
        """
        _, response = self._detail({
            "microstructure": [{
                "note": "Microstructure note",
                "grains": [{"label": "Grain", "orientation": "Random", "phase_id": 1, "grain_id": 2}],
                "voxels": [{
                    "volume": 1, "orientation": "Random", "voxel_index": [0, 0, 0],
                    "centroid_coordinates": [0.5, 0.5, 0.5], "phase_id": 1, "voxel_id": 4,
                }],
                "grid": {"note": "Grid note", "grid_spacing": [1, 1, 1], "grid_size": [2, 2, 2], "status": "active"},
                "time_point": 0,
            }],
        })
        microstructure = next(
            row for row in response.context["detail_rows"] if row["label"] == "microstructure"
        )
        fields = {row["label"]: row for row in microstructure["children"]}
        self.assertEqual(list(fields), ["time_point", "grid", "voxels", "note", "grains"])
        expected_children = {
            "grid": ["status", "grid_size", "grid_spacing", "note"],
            "grains": ["grain_id", "phase_id", "orientation", "label"],
            "voxels": ["voxel_id", "phase_id", "centroid_coordinates", "voxel_index", "orientation", "volume"],
        }
        for name, expected in expected_children.items():
            with self.subTest(group=name):
                self.assertEqual([row["label"] for row in fields[name]["children"]], expected)

    def test_current_schema_example_has_direct_fields_and_unchanged_download(self):
        """
        Exercise current field names with a reproducible synthetic simulation
        """
        data = {
            "units": {
                "Stress": "MPa", "Strain": 1, "Length": "mm",
                "Force": "N", "Angle": "degrees", "Temperature": "K",
            },
            "identifier": "synthetic-detail",
            "title": "Synthetic copper simulation",
            "creator": ["Example Researcher"],
            "creator_affiliation": ["Example University"],
            "creator_institute": ["Example Institute"],
            "creator_group": ["Example Group"],
            "date": "2026-01-01",
            "shared_with": [{"access_type": "all"}],
            "rights": "CC BY 4.0",
            "rights_holder": ["Example Researcher"],
            "software": "Example Solver",
            "software_version": "1.0",
            "system": "Linux",
            "system_version": "1.0",
            "processor_specifications": "Example processor",
            "input_path": "inputs",
            "results_path": "results",
            "RVE_size": [1, 1, 1],
            "RVE_continuity": True,
            "discretization_type": "Structured",
            "discretization_unit_size": [0.5, 0.5, 0.5],
            "discretization_count": 8,
            "origin": {
                "software": "Example Geometry Generator",
                "software_version": "1.0",
                "system": "Linux",
                "system_version": "1.0",
                "input_path": "geometry-inputs",
                "results_path": "geometry-results",
            },
            "mechanical_BC": [{
                "vertex_list": ["V000"],
                "constraints": ["fixed", "free", "free"],
            }],
            "phase": [{
                "constitutive_model": {"elastic_model_name": "Isotropic Elasticity"},
                "phase_name": "Copper",
            }],
            "stress": {"stress_11": [0, 10]},
            "total_strain": {"strain_11": [0, 0.01]},
        }
        obj, response = self._detail(data)
        rows = response.context["detail_rows"]
        fields = {row["label"]: row for row in rows}

        self.assertEqual(set(fields), set(data) - {"mechanical_BC", "stress", "total_strain"})
        self.assertEqual(list(fields)[:4], ["title", "creator", "creator_affiliation", "date"])
        self.assertEqual(list(fields)[20], "units")
        self.assertEqual(fields["shared_with"]["type"], "group")
        self.assertEqual(fields["shared_with"]["children"][0]["label"], "access_type")
        self.assertEqual(fields["creator_affiliation"]["type"], "string_list")
        self.assertEqual(fields["creator_institute"]["type"], "string_list")
        self.assertEqual(fields["creator_group"]["type"], "string_list")
        self.assertEqual(
            [row["label"] for row in fields["phase"]["children"]],
            ["phase_name", "constitutive_model"],
        )
        self.assertEqual(fields["phase"]["children"][1]["type"], "group")
        self.assertEqual(
            [row["label"] for row in fields["origin"]["children"]],
            list(data["origin"]),
        )
        self.assertTrue(response.context["plot_variables"])
        self.assertTrue(response.context["mechanical_bc_items"])
        exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(exported.json(), data)
        self.assertEqual(exported.content.decode(), json.dumps(data, indent=2, ensure_ascii=False))

    def test_detail_and_download_keep_access_rules_and_original_json(self):
        """
        Keep detail and export access aligned without altering stored JSON order
        """
        data = {
            "units": {"Stress": "MPa"},
            "custom_data": {"untouched": [3, 2, 1]},
            "title": "Access checks",
            "identifier": "original-download",
        }
        private = JSONData.objects.create(owner=self.owner, data=data, access_type="c")
        public = JSONData.objects.create(owner=self.owner, data=data, access_type="all")
        shared = JSONData.objects.create(owner=self.owner, data=data, access_type="c")
        shared.shared_users.add(self.viewer)
        cases = (
            (self.owner, private, 200),
            (self.viewer, public, 200),
            (self.viewer, shared, 200),
            (self.viewer, private, 404),
        )

        for user, obj, expected_status in cases:
            self.client.force_login(user)
            for route in ("json_data_detail", "json_data_export"):
                with self.subTest(user=user.username, obj=obj.pk, route=route):
                    response = self.client.get(reverse(route, args=[obj.pk]))
                    self.assertEqual(response.status_code, expected_status)
                    if route == "json_data_export" and expected_status == 200:
                        self.assertEqual(
                            response.content.decode(),
                            json.dumps(data, indent=2, ensure_ascii=False),
                        )
            obj.refresh_from_db()
            self.assertEqual(json.dumps(obj.data), json.dumps(data))

        self.client.logout()
        for route in ("json_data_detail", "json_data_export"):
            with self.subTest(anonymous_route=route):
                response = self.client.get(reverse(route, args=[public.pk]))
                self.assertEqual(response.status_code, 302)

    def test_repeated_array_names_have_distinct_expand_controls(self):
        """
        Connect each raw value button to its own panel across nested groups
        """
        _, response = self._detail({
            "identifier": "repeated-array-controls",
            "title": "Repeated array labels",
            "phase": [
                {"phase_name": "First", "orientation": {"euler_angles": list(range(9))}},
                {"phase_name": "Second", "orientation": {"euler_angles": list(range(9, 18))}},
            ],
            "first_series": {"values": list(range(8)), "note": "First series"},
            "second_series": {"values": list(range(8, 16)), "note": "Second series"},
            "mixed_values": [1, "two", False],
        })
        html = response.content.decode()
        targets = re.findall(
            r'<button\b[^>]*data-bs-toggle="collapse"[^>]*'
            r'data-bs-target="#([^"]+)"[^>]*>\s*Show values\s*</button>',
            html,
        )

        self.assertGreaterEqual(len(targets), 5)
        self.assertEqual(len(targets), len(set(targets)))
        for target in targets:
            self.assertEqual(html.count(f'id="{target}"'), 1)
