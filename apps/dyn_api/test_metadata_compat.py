from copy import deepcopy

from django.test import SimpleTestCase

from apps.pages.upload_test_data import valid_upload_object, variant_field_names
from .helpers import validate_json
from .metadata_compat import field_value, metadata_view


class MetadataCompatibilityTests(SimpleTestCase):
    """
    Accept equivalent metadata spellings while retaining actual requirements
    """

    def test_cpu_specifications_is_an_explicit_processor_alias(self):
        """
        Accept either requested name without rewriting the uploaded field
        """
        for name in ("CPU_specifications", "cpu specifications", "CPU-SPECIFICATIONS"):
            with self.subTest(name=name):
                data = valid_upload_object()
                value = data.pop("processor_specifications")
                data[name] = [[value]]
                before = deepcopy(data)
                self.assertEqual(validate_json([data], detailed=True), ([data], []))
                self.assertEqual(metadata_view(data)["processor_specifications"], value)
                self.assertEqual(field_value(data, "processor_specifications"), value)
                self.assertEqual(data, before)

    def test_processor_aliases_still_require_nonempty_values_at_the_same_parent(self):
        """
        Preserve emptiness and parent boundaries while accepting multiple descriptions
        """
        data = valid_upload_object(CPU_specifications=[["CPU"]])
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        data["CPU_specifications"] = "Different CPU"
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        self.assertEqual(metadata_view(data)["processor_specifications"], ["CPU", "Different CPU"])
        del data["processor_specifications"]
        data["CPU_specifications"] = [[""]]
        _, errors = validate_json([data], detailed=True)
        self.assertIn("empty_values", [error["category"] for error in errors])
        data.pop("CPU_specifications")
        data["origin"] = {"CPU_specifications": "CPU"}
        _, errors = validate_json([data], detailed=True)
        self.assertIn("processor_specifications", [field for error in errors for field in error["fields"]])

    def test_single_value_wrappers_are_recognized_without_editing_the_source(self):
        """
        Read wrapped scalars, objects and array entries using their declared shape
        """
        data = valid_upload_object(identifier=[["wrapped-id"]], title=["Wrapped simulation"])
        data["RVE_continuity"] = [[False]]
        data["creator"] = [[["Researcher"]]]
        data["discretization_count"] = [["0"]]
        data["units"] = [[{key: [[value]] for key, value in data["units"].items()}]]
        data["phase"][0]["constitutive_model"] = [data["phase"][0]["constitutive_model"]]
        data["phase"] = [[data["phase"][0]]]
        data["mechanical_BC"][0]["applied_load"] = [[{"magnitude": [[" +1.5e-2\n"]]}]]
        data["stress"] = [{"equivalent_stress": [["1.5"]]}]
        data["extra"] = [["keep this structure"]]
        data = variant_field_names(data)
        before = deepcopy(data)
        view = metadata_view(data)
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        self.assertEqual(view["identifier"], "wrapped-id")
        self.assertEqual(field_value(data, "identifier"), "wrapped-id")
        self.assertEqual(field_value(data, "title"), "Wrapped simulation")
        self.assertEqual(view["discretization_count"], 0)
        self.assertIs(view["RVE_continuity"], False)
        self.assertEqual(view["creator"], ["Researcher"])
        self.assertEqual(view["RVE_size"], [1, 1, 1])
        self.assertEqual(view["units"]["Strain"], 1)
        self.assertEqual(view["phase"][0]["constitutive_model"], {"elastic_model_name": "Hooke"})
        self.assertEqual(view["mechanical_BC"][0]["applied_load"], [{"magnitude": 0.015}])
        self.assertEqual(view["stress"]["equivalent_stress"], [1.5])
        self.assertEqual(view["EXTRA"], [["keep this structure"]])
        self.assertEqual(data, before)

    def test_wrapped_tensor_components_remain_distinct(self):
        """
        Unwrap tensor components without merging reciprocal directions
        """
        tensor = {key: [[str(index)]] for index, key in enumerate(("xx", "yy", "zz", "xy", "yz", "xz", "yx"))}
        data = valid_upload_object()
        data["mechanical_BC"][0]["applied_load"] = [{"magnitude": [[tensor]]}]
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        view = metadata_view(data)["mechanical_BC"][0]["applied_load"][0]["magnitude"]
        self.assertEqual(view["xx"], 0)
        self.assertEqual(view["xy"], 3)
        self.assertEqual(view["yx"], 6)

    def test_wrappers_cannot_hide_empty_required_values(self):
        """
        Check emptiness after removing wrappers while allowing optional blanks
        """
        for empty in (None, " \n", [], {}):
            with self.subTest(empty=empty):
                data = valid_upload_object(title=[[empty]])
                data["units"]["Stress"] = [[empty]]
                data["mechanical_BC"][0]["applied_load"] = [{"magnitude": [[empty]]}]
                valid, errors = validate_json([data], detailed=True)
                self.assertFalse(valid)
                fields = {field for error in errors if error["category"] == "empty_values" for field in error["fields"]}
                self.assertTrue({"title", "units.Stress", "mechanical_BC[1].applied_load[1].magnitude"} <= fields)
        data = valid_upload_object(origin=[[{}]], description=[[""]])
        self.assertEqual(validate_json([data], detailed=True), ([data], []))

    def test_wrapped_conditions_still_require_their_children(self):
        """
        Activate conditional requirements through wrapped array entries
        """
        data = valid_upload_object(thermal_BC=[[{"vertex_list": ["V000"], "constraints": [[[" LOADED "]]]}]])
        valid, errors = validate_json([data], detailed=True)
        self.assertFalse(valid)
        fields = {field for error in errors for field in error["fields"]}
        self.assertIn("thermal_BC[1].applied_load", fields)
        self.assertIn("thermal_BC[1].loading_mode", fields)

    def test_multiple_values_are_never_reduced_to_the_first_item(self):
        """
        Retain genuine sequences and reject ambiguous scalar magnitudes
        """
        data = valid_upload_object()
        data["stress"]["equivalent_stress"] = ["1.5"]
        self.assertEqual(metadata_view(data)["stress"]["equivalent_stress"], [1.5])
        for value in (["1.5", "2.5"], [["1.5", "2.5"]]):
            with self.subTest(value=value):
                data["mechanical_BC"][0]["applied_load"] = [{"magnitude": value}]
                view = metadata_view(data)
                self.assertEqual(view["mechanical_BC"][0]["applied_load"][0]["magnitude"], ["1.5", "2.5"])
                self.assertFalse(validate_json([data], detailed=True)[0])

    def test_wrapped_aliases_are_compared_by_their_recognized_value(self):
        """
        Accept equivalent wrappers and still report genuinely conflicting fields
        """
        data = valid_upload_object()
        data["units"]["STRESS"] = [[data["units"]["Stress"]]]
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        data["units"]["STRESS"] = [["Pa"]]
        _, errors = validate_json([data], detailed=True)
        self.assertIn("conflicting_fields", [error["category"] for error in errors])

    def test_formatted_field_names_and_numeric_strings_preserve_the_source(self):
        """
        Recognize required descendants and numbers without changing raw metadata
        """
        data = valid_upload_object(shared_with=[" ALL "])
        data["mechanical_BC"][0]["applied_load"] = [{"magnitude": " +1.25e-2\n"}]
        data["stress"]["equivalent_stress"] = ["0", "1.5"]
        data = variant_field_names(data)
        before = deepcopy(data)
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        self.assertEqual(data, before)

    def test_numeric_text_still_has_to_be_a_finite_number(self):
        """
        Reject words, unit annotations and nonfinite numbers as magnitudes
        """
        for value in ("NaN", "Infinity", "1e999", "1 MPa", "1,5", "one", True):
            with self.subTest(value=value):
                data = valid_upload_object()
                data["mechanical_BC"][0]["applied_load"] = [{"magnitude": value}]
                valid, errors = validate_json([data], detailed=True)
                self.assertFalse(valid)
                self.assertTrue(errors)

    def test_sharing_accepts_complete_tokens_and_formatted_access_keys(self):
        """
        Recognize explicit public and private declarations without access_type
        """
        for sharing in ("all", ["all"], [" C "], {"Access-Type": "ALL"}, [{"all": True}]):
            with self.subTest(sharing=sharing):
                data = valid_upload_object(shared_with=sharing)
                self.assertEqual(validate_json([data], detailed=True), ([data], []))

    def test_conflicting_spellings_are_reported_instead_of_choosing_one(self):
        """
        Reject two different values for the same functional field
        """
        data = valid_upload_object()
        data["units"]["STRESS"] = "Pa"
        valid, errors = validate_json([data], detailed=True)
        self.assertFalse(valid)
        self.assertIn("conflicting_fields", [error["category"] for error in errors])

    def test_equal_spellings_are_safe_and_missing_content_is_still_rejected(self):
        """
        Accept redundant equal values while preserving missing and empty errors
        """
        data = valid_upload_object()
        data["DATE"] = data["date"]
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        data = variant_field_names(data)
        data["TOTAL - STRAIN"] = {}
        del data["UNITS"]["STRESS"]
        valid, errors = validate_json([data], detailed=True)
        self.assertFalse(valid)
        fields = {field for error in errors for field in error["fields"]}
        self.assertIn("total_strain", fields)
        self.assertIn("units.Stress", fields)

    def test_formatted_conditional_fields_cannot_bypass_requirements(self):
        """
        Keep conditional children required after recognizing their controlling value
        """
        data = variant_field_names(valid_upload_object(
            thermal_BC=[{"vertex_list": ["V000"], "constraints": [" LOADED "]}],
        ))
        valid, errors = validate_json([data], detailed=True)
        self.assertFalse(valid)
        fields = {field for error in errors for field in error["fields"]}
        self.assertIn("thermal_BC[1].applied_load", fields)

    def test_identifier_values_and_unrelated_metadata_are_not_reinterpreted(self):
        """
        Retain text identifiers and do not invent semantic aliases or nested fields
        """
        data = valid_upload_object(identifier=123)
        _, errors = validate_json([data], detailed=True)
        self.assertIn("invalid_identifier", [error["category"] for error in errors])
        data = valid_upload_object()
        data["origin"] = {"system": data.pop("system")}
        data["Material"] = data.pop("phase")
        _, errors = validate_json([data], detailed=True)
        fields = {field for error in errors for field in error["fields"]}
        self.assertIn("system", fields)
        self.assertIn("phase", fields)
