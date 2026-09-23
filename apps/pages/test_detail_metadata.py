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

    def test_schema_order_survives_reversed_and_database_key_order(self):
        """
        Present names before simulation details regardless of stored key order
        """
        expected = [
            "identifier", "title", "creator", "creator_ORCID",
            "creator_affiliation", "date", "software", "software_version",
            "system", "processor_specifications", "RVE_size",
            "discretization_type", "mechanical_BC", "phase", "stress", "units",
        ]
        orders = (
            list(reversed(expected)),
            sorted(expected, key=lambda key: (len(key), key)),
        )

        for keys in orders:
            with self.subTest(keys=keys):
                data = {key: f"Value for {key}" for key in keys}
                obj, response = self._detail(data)
                displayed = [
                    row["label"] for row in response.context["detail_rows"]
                    if row["label"] in expected
                ]

                self.assertEqual(displayed, expected)
                html = response.content.decode()
                positions = [html.index(f">{key}</") for key in expected]
                self.assertEqual(positions, sorted(positions))
                obj.refresh_from_db()
                self.assertEqual(json.dumps(obj.data), json.dumps(data))

    def test_additional_metadata_follows_schema_fields_and_escapes_uploads(self):
        """
        Keep unknown top level fields together and escape their labels and values
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
        additional = rows[-1]

        self.assertEqual(additional["label"], "Additional metadata")
        self.assertEqual(additional["type"], "group")
        self.assertEqual(
            [row["label"] for row in additional["children"]],
            [uploaded_label, "$schema", "custom_flag"],
        )
        self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
        self.assertContains(response, "&lt;script&gt;alert(&quot;metadata&quot;)&lt;/script&gt;")
        self.assertNotContains(response, uploaded_label)
        self.assertNotContains(response, uploaded_value)
        self.assertContains(response, "https://example.test/metadata.schema.json")

    def test_optional_fields_are_shown_only_when_supplied(self):
        """
        Display supplied optional metadata without inventing missing optional rows
        """
        _, response = self._detail({
            "creator_ORCID": ["0000-0002-1451-2715"],
            "identifier": "optional-fields",
            "title": "Optional metadata",
        })
        labels = [row["label"] for row in response.context["detail_rows"]]

        self.assertIn("creator_ORCID", labels)
        self.assertNotIn("thermal_BC", labels)
        self.assertNotIn("user_extra_information", labels)
        self.assertNotIn("system_extra_information", labels)
        self.assertNotIn("Additional metadata", labels)
        self.assertContains(response, "0000-0002-1451-2715")

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
                "phase / Item 1 / phase_name", "phase / Item 1 / phase_id",
                "phase / Item 1 / volume_fraction",
                "phase / Item 1 / orientation / euler_angles",
                "phase / Item 1 / orientation / grain_count",
                "phase / Item 1 / orientation / custom_orientation",
                "phase / Item 1 / custom_note",
                "phase / Item 2 / phase_name", "phase / Item 2 / phase_id",
                "phase / Item 2 / orientation / euler_angles",
                "phase / Item 2 / orientation / grain_count",
                "phase / Item 2 / custom_note",
            ],
        )
        self.assertEqual(
            [row["value"] for row in rows],
            [
                "First phase", 2, 0.7, [30, 20, 10], 8,
                "Extra orientation data", "First phase note",
                "Second phase", 1, [60, 50, 40], 13, "Second phase note",
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
        additional = response.context["detail_rows"][-1]

        self.assertEqual(additional["label"], "Additional metadata")
        fields = {row["label"]: row for row in additional["children"]}
        self.assertEqual(
            list(fields),
            ["phase.note", "title / explanation", "units[custom]", "a.b", "a"],
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
        self.assertTrue(all(row["type"] == "empty" for row in rows))
        self.assertNotIn("Additional metadata", [row["label"] for row in rows])

    def test_legacy_names_keep_their_labels_at_related_schema_positions(self):
        """
        Place older template names beside canonical fields without renaming them
        """
        rows = _build_detail_rows({
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
        })
        labels = [row["label"] for row in rows]

        self.assertEqual(
            [label for label in labels if label.startswith("origin / ")],
            [
                "origin / software", "origin / software Version", "origin / system",
                "origin / system Version", "origin / Input Path", "origin / Results Path",
            ],
        )
        self.assertEqual(
            [label for label in labels if label.startswith("phase / ")],
            [
                "phase / phase_name", "phase / phase_id",
                "phase / phase_identifier", "phase / volume_fraction",
            ],
        )
        self.assertLess(labels.index("system_version"), labels.index("CPU_specifications"))
        self.assertEqual(
            abs(labels.index("processor_specifications") - labels.index("CPU_specifications")),
            1,
        )
        self.assertLess(labels.index("CPU_specifications"), labels.index("input_path"))

    def test_visualizations_keep_their_original_fields_and_unplotted_metadata(self):
        """
        Keep raw mechanical metadata available alongside plots and boundary views
        """
        _, response = self._detail({
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
        })
        by_label = {row["label"]: row for row in response.context["detail_rows"]}

        for key in ("mechanical_BC", "stress", "total_strain", "plastic_strain"):
            with self.subTest(field=key):
                self.assertIn(key, by_label)
                self.assertEqual(by_label[key]["type"], "group")
        for note in (
            "Boundary condition provenance", "Measured stress note",
            "Total strain note", "Plastic strain note",
        ):
            self.assertContains(response, note)
        variables = {item["key"]: item for item in response.context["plot_variables"]}
        self.assertEqual(variables["stress.stress_11"]["values"], [0, 10])
        self.assertEqual(variables["total_strain.strain_11"]["values"], [0, 0.1])
        self.assertEqual(variables["plastic_strain.plastic_strain_11"]["values"], [0, 0.01])
        self.assertTrue(response.context["mechanical_bc_items"])

    def test_additional_metadata_keeps_empty_and_mixed_values(self):
        """
        Retain uploaded empty containers, nulls, and mixed arrays in the extra group
        """
        _, response = self._detail({
            "identifier": "empty-extra-values",
            "title": "Extra value types",
            "empty_object": {},
            "empty_list": [],
            "null_value": None,
            "mixed_values": [1, "two", False],
        })
        additional = response.context["detail_rows"][-1]

        self.assertEqual(additional["label"], "Additional metadata")
        by_label = {row["label"]: row for row in additional["children"]}
        self.assertEqual(json.loads(by_label["empty_object"]["json_value"]), {})
        self.assertEqual(json.loads(by_label["empty_list"]["json_value"]), [])
        self.assertEqual(by_label["null_value"]["type"], "empty")
        self.assertEqual(json.loads(by_label["mixed_values"]["json_value"]), [1, "two", False])

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
