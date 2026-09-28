from copy import deepcopy

from django.test import SimpleTestCase

from apps.pages.upload_test_data import valid_upload_object, variant_field_names
from .helpers import validate_json


class MetadataCompatibilityTests(SimpleTestCase):
    """
    Accept equivalent metadata spellings while retaining actual requirements
    """

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
        Reject two different values for the same recognized field
        """
        data = valid_upload_object()
        data["DATE"] = "1999-01-01"
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
