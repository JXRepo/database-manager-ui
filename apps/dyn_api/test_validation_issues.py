from copy import deepcopy

from django.test import SimpleTestCase

from .helpers import validate_json
from apps.pages.upload_test_data import valid_upload_object


class DetailedValidationTests(SimpleTestCase):
    """
    Keep upload issues grouped by object and category without changing validation
    """

    def setUp(self):
        """
        Create an object with every required top-level field
        """
        self.valid = valid_upload_object(discretization_count=0)

    def test_detailed_issues_preserve_object_order_and_separate_missing_and_empty(self):
        """
        Report each category once with every affected field and its original object index
        """
        mixed = deepcopy(self.valid)
        del mixed["title"]
        del mixed["phase"]
        mixed["creator"] = []
        mixed["rights"] = " "
        mixed["identifier"] = 42
        last = dict(self.valid)
        del last["units"]

        valid, issues = validate_json([self.valid, mixed, "invalid object", last], detailed=True)

        self.assertEqual(valid, [self.valid])
        self.assertEqual(issues, [
            {"object_index": 2, "category": "missing_required", "fields": ["title", "phase"], "message": ""},
            {"object_index": 2, "category": "empty_values", "fields": ["creator", "rights"], "message": ""},
            {"object_index": 2, "category": "invalid_identifier", "fields": [],
             "message": "Identifier must be a text value."},
            {"object_index": 3, "category": "invalid_structure", "fields": [],
             "message": "This data object must be a JSON object."},
            {"object_index": 4, "category": "missing_required", "fields": ["units"], "message": ""},
        ])

    def test_detailed_validation_rejects_every_empty_required_value(self):
        """
        Keep null and all supported empty containers in the empty values category
        """
        for value in (None, "", " \t\n", [], {}):
            with self.subTest(value=value):
                valid, issues = validate_json([dict(self.valid, title=value)], detailed=True)
                self.assertEqual(valid, [])
                self.assertEqual(issues, [
                    {"object_index": 1, "category": "empty_values", "fields": ["title"], "message": ""},
                ])

    def test_detailed_validation_keeps_zero_false_optional_and_nested_values(self):
        """
        Accept optional blanks while required descendants stay valid
        """
        data = deepcopy(self.valid)
        data.update({"optional_note": "", "optional_list": [], "optional_object": {}})
        data["phase"][0]["nested_optional_value"] = None
        before = deepcopy(data)

        for detailed in (False, True):
            with self.subTest(detailed=detailed):
                self.assertEqual(validate_json([data], detailed=detailed), ([data], []))
                self.assertEqual(data, before)

    def test_detailed_validation_allows_missing_blank_and_valid_identifiers(self):
        """
        Leave identifier generation to upload while preserving supplied text identifiers
        """
        objects = [self.valid]
        objects.extend(dict(self.valid, identifier=value) for value in (None, "", " \t", "valid-id"))
        before = deepcopy(objects)

        self.assertEqual(validate_json(objects, detailed=True), (objects, []))
        self.assertEqual(objects, before)

    def test_invalid_identifier_issues_contain_facts_without_repeating_guidance(self):
        """
        Identify malformed supplied identifiers with the original object positions
        """
        values = [42, True, [], {}, " leading", "trailing "]
        objects = [self.valid] + [dict(self.valid, identifier=value) for value in values]

        valid, issues = validate_json(objects, detailed=True)

        self.assertEqual(valid, [self.valid])
        self.assertEqual([issue["object_index"] for issue in issues], [2, 3, 4, 5, 6, 7])
        for index, issue in enumerate(issues):
            self.assertEqual(issue["category"], "invalid_identifier")
            self.assertEqual(issue["fields"], [])
            self.assertEqual(issue["message"], "Identifier must be a text value." if index < 4 else
                             "Identifier has leading or trailing whitespace.")

    def test_default_validation_preserves_existing_string_messages(self):
        """
        Retain the existing string interface for callers that do not request details
        """
        mixed = dict(self.valid, creator=[], identifier=42)
        del mixed["title"]
        missing = dict(self.valid)
        del missing["phase"]
        objects = [mixed, missing, dict(self.valid, title=""), 42,
                   dict(self.valid, identifier=False), dict(self.valid, identifier=" padded ")]

        valid, errors = validate_json(objects)

        self.assertEqual(valid, [])
        self.assertEqual(errors, [
            "Data object 1: missing required field: title; empty required field: creator. "
            "Please add the missing required fields and fill in the empty required fields, "
            "then upload the JSON file again.",
            "Data object 2: missing required field: phase. "
            "Please add the missing required field and upload the JSON file again.",
            "Data object 3: empty required field: title. "
            "Please fill in the empty required field and upload the JSON file again.",
            "Data object 4: not a valid JSON object",
            "Data object 5: identifier must be a text value. "
            "Please use a JSON string, or omit identifier to generate one automatically.",
            "Data object 6: identifier has leading or trailing whitespace. "
            "Please remove the surrounding whitespace and upload the JSON file again.",
        ])
