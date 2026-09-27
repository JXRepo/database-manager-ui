from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.pages.upload_test_data import valid_upload_object
from .helpers import REQUIRED_TOP_LEVEL_FIELDS, validate_json


class RequiredSchemaTests(SimpleTestCase):
    """
    Exercise nested and conditional required fields without changing source data
    """

    def issues(self, data):
        """
        Collect field paths by issue category

        Parameters
        ----------
        data : dict
            Metadata to validate.

        Returns
        -------
        dict
            Categories containing affected paths.
        """
        _, errors = validate_json([data], detailed=True)
        result = {}
        for error in errors:
            result.setdefault(error["category"], []).extend(error["fields"])
        return result

    def test_nested_missing_and_empty_fields_are_all_reported(self):
        """
        Report separate nested defects together in their original object
        """
        data = valid_upload_object()
        del data["phase"][0]["phase_name"]
        data["phase"][0]["constitutive_model"] = {}
        data["units"]["Stress"] = "  "
        self.assertEqual(self.issues(data), {
            "missing_required": ["phase[1].phase_name"],
            "empty_values": ["phase[1].constitutive_model", "units.Stress"],
        })

    def test_every_empty_value_is_rejected_in_required_children(self):
        """
        Treat null, whitespace and empty containers consistently at all levels
        """
        for value in (None, "", " \t", [], {}):
            with self.subTest(value=value):
                data = valid_upload_object()
                data["units"]["Stress"] = value
                self.assertEqual(self.issues(data), {"empty_values": ["units.Stress"]})

    def test_optional_empty_fields_zero_and_false_are_preserved(self):
        """
        Leave optional blanks intact and do not mistake zero or false for emptiness
        """
        data = valid_upload_object(thermal_BC=[], microstructure=None, description=" ",
                                   extra={"note": None}, discretization_count=0)
        data["phase"][0]["orientation"] = {}
        data["mechanical_BC"][0]["applied_load"] = [{"magnitude": 0, "frequency": None}]
        before = deepcopy(data)
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        self.assertEqual(data, before)

    def test_thermal_required_fields_activate_only_for_a_supplied_loaded_condition(self):
        """
        Require load metadata only once its controlling field says loaded
        """
        data = valid_upload_object(thermal_BC=[{"vertex_list": ["V000"], "constraints": ["free"]}])
        self.assertEqual(self.issues(data), {})
        data["thermal_BC"][0]["constraints"] = ["loaded"]
        data["thermal_BC"][0]["loading_mode"] = ""
        self.assertEqual(self.issues(data), {
            "missing_required": ["thermal_BC[1].applied_load"],
            "empty_values": ["thermal_BC[1].loading_mode"],
        })
        del data["thermal_BC"][0]["constraints"]
        self.assertEqual(self.issues(data), {"missing_required": ["thermal_BC[1].constraints"]})

    def test_mechanical_load_is_optional_but_its_entries_require_magnitude(self):
        """
        Do not invent a mechanical applied_load requirement
        """
        data = valid_upload_object()
        self.assertEqual(self.issues(data), {})
        data["mechanical_BC"][0]["applied_load"] = [{"step": 0}, {"magnitude": None}]
        self.assertEqual(self.issues(data), {
            "missing_required": ["mechanical_BC[1].applied_load[1].magnitude"],
            "empty_values": ["mechanical_BC[1].applied_load[2].magnitude"],
        })

    def test_tensor_orientation_and_referenced_microstructure_requirements(self):
        """
        Reach required descendants through alternatives and trusted schema references
        """
        data = valid_upload_object(microstructure=[{"time_point": 0, "grid": {"status": "undeformed"},
                                                  "voxels": [{}]}])
        data["mechanical_BC"][0]["applied_load"] = [{"magnitude": {"xx": 0}}]
        data["phase"][0]["orientation"] = {"grain_count": 0, "euler_angles": {"Phi": [0]}}
        fields = self.issues(data)["missing_required"]
        for field in ("mechanical_BC[1].applied_load[1].magnitude.xy",
                      "phase[1].orientation.euler_angles.Phi1", "phase[1].orientation.texture_type",
                      "microstructure[1].grid.grid_spacing", "microstructure[1].voxels[1].voxel_id"):
            self.assertIn(field, fields)

    def test_wrong_container_cannot_bypass_required_descendants(self):
        """
        Reject scalar substitutes for containers with mandatory children
        """
        for field in ("phase", "mechanical_BC", "units"):
            with self.subTest(field=field):
                self.assertIn(field, self.issues(valid_upload_object(**{field: "metadata"}))["invalid_structure"])

    def test_shared_access_type_and_conditional_access_list_are_required(self):
        """
        Validate presence rules while leaving platform permission decisions separate
        """
        self.assertEqual(self.issues(valid_upload_object(shared_with=[{}])), {
            "missing_required": ["shared_with[1].access_type"],
        })
        self.assertEqual(self.issues(valid_upload_object(shared_with=[{"access_type": "u", "access_list": []}])), {
            "empty_values": ["shared_with[1].access_list"],
        })

    def test_required_parent_with_empty_content_is_rejected_without_inventing_children(self):
        """
        Require a nonempty strain object without making an optional curve mandatory
        """
        self.assertEqual(self.issues(valid_upload_object(total_strain={})), {"empty_values": ["total_strain"]})
        self.assertEqual(self.issues(valid_upload_object(total_strain={"strain_11": [0]})), {})

    def test_pinned_sources_match_their_checksums_and_existing_root_field_list(self):
        """
        Keep the trusted schema snapshot and identifier input fields aligned
        """
        directory = Path(__file__).with_name("schemas")
        for source in json.loads((directory / "sources.json").read_text()):
            self.assertEqual(hashlib.sha256((directory / source["file"]).read_bytes()).hexdigest(), source["sha256"])
        schema = json.loads((directory / "mechanical.json").read_text())
        self.assertEqual([field for field in schema["required"] if field != "identifier"], REQUIRED_TOP_LEVEL_FIELDS)

    def test_uploaded_schema_urls_are_preserved_but_never_fetched(self):
        """
        Validate against the platform snapshot regardless of a supplied schema URL
        """
        data = valid_upload_object(**{"$schema": "https://example.invalid/untrusted-schema.json"})
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network request")):
            self.assertEqual(validate_json([data], detailed=True), ([data], []))
