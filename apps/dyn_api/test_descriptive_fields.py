from copy import deepcopy

from django.test import SimpleTestCase

from apps.pages.upload_test_data import valid_upload_object
from .helpers import validate_json
from .metadata_compat import field_value, metadata_view


class DescriptiveFieldTests(SimpleTestCase):
    """
    Recognize descriptive field keywords without weakening scientific requirements
    """

    def test_processor_names_accept_all_keywords_and_simple_plurals(self):
        """
        Accept complete descriptive names with extra words and different formatting
        """
        for name in ("processor_specification", "processor_specification_of",
                     "Specifications of Processor", "PROCESSORS-SPECIFICATIONS-A",
                     "processorSpecificationOf", "pRoCeSsOr_sPeCiFiCaTiOn_Of",
                     "CPU_specification", "CPU specifications B"):
            with self.subTest(name=name):
                data = valid_upload_object()
                data[name] = [[data.pop("processor_specifications")]]
                before = deepcopy(data)
                self.assertEqual(validate_json([data], detailed=True), ([data], []))
                self.assertEqual(metadata_view(data)["processor_specifications"], "CPU")
                self.assertEqual(field_value(data, "processor_specifications"), "CPU")
                self.assertEqual(data, before)

    def test_multiple_descriptions_retain_every_distinct_value(self):
        """
        Accept different matching values without choosing one or editing the source
        """
        data = valid_upload_object(processor_specification_A="Intel", CPU_specifications="AMD")
        before = deepcopy(data)
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        expected = ["CPU", "Intel", "AMD"]
        self.assertEqual(metadata_view(data)["processor_specifications"], expected)
        self.assertEqual(field_value(data, "processor_specifications"), expected)
        self.assertEqual(data, before)

    def test_one_nonempty_description_satisfies_the_requirement(self):
        """
        Require real content in at least one of the matching fields
        """
        data = valid_upload_object(processor_specifications="", processor_specification_A=[[None]],
                                   processor_specification_B="AMD")
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        self.assertEqual(metadata_view(data)["processor_specifications"], "AMD")
        for empty in (None, " \n", [], {}, [[""]], ["", None, []]):
            with self.subTest(empty=empty):
                data["processor_specification_B"] = empty
                valid, errors = validate_json([data], detailed=True)
                self.assertFalse(valid)
                fields = {field for error in errors if error["category"] == "empty_values"
                          for field in error["fields"]}
                self.assertIn("processor_specifications", fields)
                self.assertNotIn("conflicting_fields", [error["category"] for error in errors])

    def test_words_must_be_in_one_field_name_in_the_correct_parent(self):
        """
        Do not fill requirements using partial names, values or another parent
        """
        for extras in ({"processor": "CPU", "specification": "CPU"},
                       {"notes": "processor specification CPU"},
                       {"origin": {"processor_specification_of": "CPU"}},
                       {"processor_speculative": "CPU"}):
            with self.subTest(extras=extras):
                data = valid_upload_object(**extras)
                del data["processor_specifications"]
                valid, errors = validate_json([data], detailed=True)
                self.assertFalse(valid)
                fields = {field for error in errors if error["category"] == "missing_required"
                          for field in error["fields"]}
                self.assertIn("processor_specifications", fields)

    def test_more_specific_names_do_not_satisfy_another_requirement(self):
        """
        Keep versions, affiliations and unrelated extra information distinct
        """
        for required, extra in (("system", "system_version_notes"),
                                ("system", "system_extra_information"),
                                ("creator", "creator_affiliation_notes"),
                                ("rights", "rights_holder_notes"),
                                ("date", "updated")):
            with self.subTest(required=required, extra=extra):
                data = valid_upload_object(**{extra: "Provided"})
                del data[required]
                valid, errors = validate_json([data], detailed=True)
                self.assertFalse(valid)
                self.assertIn(required, [field for error in errors for field in error["fields"]])

    def test_nested_descriptions_are_matched_only_at_their_schema_path(self):
        """
        Accept phase name variants while retaining required material structure
        """
        data = valid_upload_object()
        phase = data["phase"][0]
        del phase["phase_name"]
        phase.update(phase_name_A="Copper", name_of_phase_B="Nickel")
        self.assertEqual(validate_json([data], detailed=True), ([data], []))
        self.assertEqual(metadata_view(data)["phase"][0]["phase_name"], ["Copper", "Nickel"])
        data["Material"] = data.pop("phase")
        self.assertFalse(validate_json([data], detailed=True)[0])

    def test_one_ambiguous_name_does_not_fill_two_different_requirements(self):
        """
        Keep multiple candidates for one description distinct from ambiguous meaning
        """
        data = valid_upload_object(software_system="Solver on Linux")
        del data["software"]
        del data["system"]
        _, errors = validate_json([data], detailed=True)
        fields = {field for error in errors for field in error["fields"]}
        self.assertTrue({"software", "system"} <= fields)

    def test_functional_fields_keep_exact_name_and_conflict_checks(self):
        """
        Preserve units, permissions, identifiers, arrays and load component meaning
        """
        for required in ("units", "shared_with", "RVE_size", "mechanical_BC", "stress", "total_strain"):
            with self.subTest(required=required):
                data = valid_upload_object()
                data[required + "_extra"] = data.pop(required)
                self.assertFalse(validate_json([data], detailed=True)[0])
        for extra in ({"UNITS": {"Stress": "Pa"}}, {"SHARED-WITH": ["all"]},
                      {"IDENTIFIER": "different"}):
            with self.subTest(extra=extra):
                data = valid_upload_object(identifier="original", **extra)
                _, errors = validate_json([data], detailed=True)
                self.assertIn("conflicting_fields", [error["category"] for error in errors])
        data = valid_upload_object(identifier_notes="not-an-identifier")
        self.assertIsNone(field_value(data, "identifier"))
        data["mechanical_BC"][0]["applied_load"] = [{"magnitude_extra": 1}]
        _, errors = validate_json([data], detailed=True)
        self.assertIn("mechanical_BC[1].applied_load[1].magnitude",
                      [field for error in errors for field in error["fields"]])
