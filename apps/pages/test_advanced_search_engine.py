import json
from copy import deepcopy
from pathlib import Path
from unittest import TestCase

from django.http import QueryDict

from .advanced_search import (
    DATA_FIELD_CHOICES,
    get_field_operators,
    matches_conditions,
    parse_conditions,
)


def condition_query(*rows):
    """
    Build repeated form parameters without invoking a view

    Parameters
    ----------
    *rows : tuple
        Field token or JSON path, operator, first value, and optional second value.

    Returns
    -------
    QueryDict
        Parameters in the same order as submitted form rows.
    """
    query = QueryDict(mutable=True, encoding="utf-8")
    for row in rows:
        for index, name in enumerate(("field", "operator", "value", "value_to")):
            query.appendlist("condition_" + name, row[index] if index < len(row) else "")
    return query


class AdvancedSearchConditionTests(TestCase):
    """
    Validate user input before allowing field conditions to run
    """

    def test_blank_rows_do_not_create_conditions(self):
        """
        Ignore untouched rows instead of rejecting the initial form
        """
        for query in (QueryDict(encoding="utf-8"), condition_query(("", "contains", "", ""))):
            with self.subTest(query=query):
                rows, conditions, errors = parse_conditions(query)
                self.assertEqual(conditions, [])
                self.assertEqual(errors, [])

    def test_valid_path_is_canonicalized_without_changing_key_names(self):
        """
        Keep exact unusual keys while normalizing submitted JSON whitespace
        """
        rows, conditions, errors = parse_conditions(condition_query(
            ('[ "phase", "Grain.Number", "α β" ]', "gte", "1e2", ""),
        ))
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["field"], '["phase","Grain.Number","α β"]')
        self.assertTrue(matches_conditions({"phase": {"Grain.Number": {"α β": 100}}}, conditions))

    def test_named_field_tokens_compile_without_becoming_json_paths(self):
        """
        Preserve fixed selection tokens while preparing named key matching
        """
        rows, conditions, errors = parse_conditions(condition_query(("Texture_Type", "contains", "random")))
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["field"], "Texture_Type")
        self.assertEqual(conditions, [{"field_key": "Texture_Type", "operator": "contains", "value": "random"}])

    def test_numeric_named_fields_reject_text_operators_without_losing_rows(self):
        """
        Require numeric comparisons and preserve incompatible submitted intent

        A stale or manually edited URL must be corrected before any rows run.
        """
        for field in ("Grain_Number", "Element_Number", "Scaling_Factor", "Max_Total_Strain"):
            for operation in ("contains", "exact"):
                with self.subTest(field=field, operation=operation):
                    rows, conditions, errors = parse_conditions(condition_query(
                        ("Texture_Type", "exact", "random"),
                        (field, operation, " 150 ", ""),
                    ))
                    self.assertTrue(errors)
                    self.assertEqual(conditions, [])
                    self.assertEqual(rows[1]["field"], field)
                    self.assertEqual(rows[1]["operator"], operation)
                    self.assertEqual(rows[1]["value"], " 150 ")
                    self.assertEqual(rows[1]["value_to"], "")
                    self.assertIn(field, rows[1]["error"])

    def test_text_named_fields_reject_numeric_operators_without_losing_values(self):
        """
        Reject numeric comparisons even when a text query looks like a number

        Validation must retain range bounds so the user can correct the row.
        """
        fields = ("Hash_Orientation", "Texture_Type", "Load_Type", "Stress_Type", "Load_Descriptor", "Hash_load")
        for field in fields:
            for operation in ("eq", "gt", "gte", "lt", "lte", "between"):
                upper = "8" if operation == "between" else ""
                with self.subTest(field=field, operation=operation):
                    rows, conditions, errors = parse_conditions(condition_query((field, operation, "2", upper)))
                    self.assertTrue(errors)
                    self.assertEqual(conditions, [])
                    self.assertEqual(rows[0]["field"], field)
                    self.assertEqual(rows[0]["operator"], operation)
                    self.assertEqual(rows[0]["value"], "2")
                    self.assertEqual(rows[0]["value_to"], upper)
                    self.assertIn(field, rows[0]["error"])

    def test_field_operator_choices_are_ordered_for_each_type_and_legacy_fields(self):
        """
        Give the form the same permitted comparisons that the parser accepts

        Legacy paths and unrecognized tokens retain the complete operator list.
        """
        numeric = ("eq", "gt", "gte", "lt", "lte", "between")
        text = ("contains", "exact")
        all_operators = ("contains", "exact", "eq", "gt", "gte", "lt", "lte", "between")
        cases = (
            ("Grain_Number", numeric), ("Element_Number", numeric),
            ("Scaling_Factor", numeric), ("Max_Total_Strain", numeric),
            ("Hash_Orientation", text), ("Texture_Type", text),
            ("Load_Type", text), ("Stress_Type", text),
            ("Load_Descriptor", text), ("Hash_load", text),
            ("Material_parameters", all_operators), ("", all_operators),
            ('["phase","Grain_Number"]', all_operators),
            ("Unknown_Field", all_operators),
        )
        for field, expected in cases:
            with self.subTest(field=field):
                self.assertEqual(get_field_operators(field), expected)

    def test_unknown_and_common_field_tokens_fail_closed(self):
        """
        Reject arbitrary named keys without dropping other submitted intent
        """
        for field in ("Grain_Number_Extra", "Unknown_Field", "Owner", "Abaqus-Version",
                      "identifier", "creator", "software", "keywords"):
            with self.subTest(field=field):
                rows, conditions, errors = parse_conditions(condition_query(
                    ("Grain_Number", "gt", "100"), (field, "contains", "steel"),
                ))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
                self.assertEqual(rows[1]["field"], field)
                self.assertTrue(rows[1]["error"])

    def test_partial_rows_fail_without_discarding_form_values(self):
        """
        Reject incomplete intent rather than silently broadening the search
        """
        invalid_rows = [
            ("", "contains", "steel", ""),
            ('["phase"]', "contains", "", ""),
            ("", "gt", "", ""),
            ('["phase"]', "", "steel", ""),
            ('["phase"]', "between", "1", ""),
            ('["phase"]', "contains", "steel", "unexpected"),
        ]
        for submitted in invalid_rows:
            with self.subTest(row=submitted):
                rows, conditions, errors = parse_conditions(condition_query(submitted))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
                self.assertEqual(rows[0]["value"], submitted[2])
                self.assertTrue(rows[0]["error"])

    def test_invalid_paths_and_operators_are_rejected(self):
        """
        Reject malformed or technical paths before object traversal
        """
        paths = ["phase.Grain_Number", "null", "{}", "[]", '[1]', '[true]', '[""]',
                 '[["phase"]]', '["input_path"]', '["phase","$schema"]',
                 "[" * 400 + "]" * 400]
        for field in paths:
            with self.subTest(field=field):
                rows, conditions, errors = parse_conditions(condition_query((field, "eq", "1")))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
                self.assertEqual(rows[0]["field"], field)
        rows, conditions, errors = parse_conditions(condition_query(('["phase"]', "regex", ".*")))
        self.assertTrue(errors)
        self.assertEqual(conditions, [])

    def test_numeric_input_requires_a_finite_number(self):
        """
        Reject special values and nonnumeric strings accepted by loose parsers
        """
        for value in ("NaN", "sNaN", "Infinity", "-Infinity", "true", "1_000", "3 GPa", "1e", " "):
            with self.subTest(value=value):
                rows, conditions, errors = parse_conditions(condition_query(('["number"]', "eq", value)))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
                self.assertEqual(rows[0]["value"], value)

    def test_reversed_range_is_invalid_but_equal_bounds_are_allowed(self):
        """
        Keep inclusive boundary matches while catching reversed ranges
        """
        rows, conditions, errors = parse_conditions(condition_query(('["number"]', "between", "3", "2")))
        self.assertTrue(errors)
        self.assertEqual(conditions, [])
        rows, conditions, errors = parse_conditions(condition_query(('["number"]', "between", "2", "2")))
        self.assertEqual(errors, [])
        self.assertTrue(matches_conditions({"number": 2}, conditions))

    def test_a_valid_row_does_not_hide_an_invalid_row(self):
        """
        Reject the whole set when one submitted condition is invalid
        """
        rows, conditions, errors = parse_conditions(condition_query(
            ('["phase"]', "contains", "steel"),
            ('["number"]', "gt", "not numeric"),
        ))
        self.assertTrue(errors)
        self.assertEqual(conditions, [])
        self.assertEqual(len(rows), 2)

    def test_misaligned_repeated_parameters_fail_closed(self):
        """
        Prevent shifted or missing list entries from changing condition meaning
        """
        query = condition_query(('["phase"]', "contains", "steel"))
        query.appendlist("condition_field", '["number"]')
        rows, conditions, errors = parse_conditions(query)
        self.assertTrue(errors)
        self.assertEqual(conditions, [])
        query = condition_query(('["phase"]', "contains", "steel"))
        del query["condition_operator"]
        self.assertTrue(parse_conditions(query)[2])

    def test_single_value_callers_can_omit_upper_bound_parameters(self):
        """
        Accept minimal URLs that have no range operators
        """
        query = condition_query(('["phase"]', "contains", "steel"))
        del query["condition_value_to"]
        rows, conditions, errors = parse_conditions(query)
        self.assertEqual(errors, [])
        self.assertTrue(matches_conditions({"phase": "steel"}, conditions))

    def test_condition_count_and_input_lengths_are_bounded(self):
        """
        Reject oversized requests without silently dropping active conditions
        """
        submitted = ('["phase"]', "contains", "steel")
        self.assertEqual(parse_conditions(condition_query(*([submitted] * 10)))[2], [])
        rows, conditions, errors = parse_conditions(condition_query(*([submitted] * 11)))
        self.assertTrue(errors)
        self.assertEqual(conditions, [])
        self.assertLessEqual(len(rows), 10)
        for field, value in ((json.dumps(["x" * 1024]), "x"), ('["phase"]', "x" * 201)):
            with self.subTest(field=field, value=value):
                self.assertTrue(parse_conditions(condition_query((field, "contains", value)))[2])
        self.assertEqual(parse_conditions(condition_query(('["phase"]', "contains", "x" * 200)))[2], [])

    def test_excessive_path_depth_is_rejected(self):
        """
        Bound recursive path evaluation before inspecting stored JSON
        """
        self.assertTrue(parse_conditions(condition_query((json.dumps(["key"] * 33), "eq", "1")))[2])

    def test_invalid_unicode_path_cannot_break_form_rendering(self):
        """
        Reject lone JSON surrogate escapes before creating HTML field values
        """
        rows, conditions, errors = parse_conditions(condition_query(('["\\ud800"]', "contains", "steel")))
        self.assertTrue(errors)
        self.assertEqual(conditions, [])
        self.assertEqual(rows[0]["field"], '["\\ud800"]')

    def test_numeric_range_upper_values_have_the_same_validation(self):
        """
        Reject invalid upper bounds and unmatched repeated upper parameters
        """
        for upper in ("NaN", "9 GPa", "1" * 201):
            with self.subTest(upper=upper):
                self.assertTrue(parse_conditions(condition_query(('["number"]', "between", "1", upper)))[2])
        query = condition_query(('["number"]', "eq", "1"))
        query.appendlist("condition_value_to", "2")
        self.assertTrue(parse_conditions(query)[2])


class ExamplePresetSearchTests(TestCase):
    """
    Exercise the preset catalog against the repository's real simulation files
    """

    example_rows = (
        ("texture_type", "exact", "GOSS"),
        ("grain_count", "eq", "343"),
        ("lattice_structure", "exact", "FCC"),
        ("orientation_identifier", "exact", "0abb1"),
        ("discretization_type", "exact", "Structured"),
        ("discretization_count", "eq", "2744"),
        ("RVE_continuity", "is", "true"),
        ("elastic_model_name", "contains", "anisotropic elasticity"),
        ("plastic_model_name", "exact", "crystal plasticity"),
        ("loading_type", "exact", "force"),
        ("loading_mode", "exact", "static"),
        ("global_temperature", "eq", "298"),
    )

    @classmethod
    def setUpClass(cls):
        """
        Read portable synthetic data and any locally available public examples
        """
        super().setUpClass()
        fixture = Path(__file__).with_name("fixtures") / "search_fields.json"
        cls.example = json.loads(fixture.read_text(encoding="utf-8"))
        example_dir = Path(__file__).resolve().parents[2] / "example_json_files"
        cls.examples = {}
        for path in sorted(example_dir.glob("*.json")):
            cls.examples[path.name] = json.loads(path.read_text(encoding="utf-8"))

    def test_every_offered_preset_matches_the_repository_examples(self):
        """
        Verify every offered preset against the complete tracked schema example
        """
        rows_by_field = {row[0]: row for row in self.example_rows}
        self.assertEqual(set(dict(DATA_FIELD_CHOICES)), set(rows_by_field))
        for field, label in DATA_FIELD_CHOICES:
            with self.subTest(field=field):
                rows, conditions, errors = parse_conditions(condition_query(rows_by_field[field]))
                self.assertEqual(errors, [])
                self.assertTrue(matches_conditions(self.example, conditions))
                if field == "lattice_structure":
                    continue
                for name, data in self.examples.items():
                    with self.subTest(example=name):
                        self.assertTrue(matches_conditions(data, conditions))

    def test_presets_find_fields_beneath_a_moved_simulation_object(self):
        """
        Keep presets usable when simulations gain extra container levels
        """
        for row in self.example_rows:
            with self.subTest(field=row[0]):
                rows, conditions, errors = parse_conditions(condition_query(row))
                self.assertEqual(errors, [])
                self.assertTrue(matches_conditions({"simulation": [self.example]}, conditions))

    def test_grain_count_searches_both_orientation_and_phase_counts(self):
        """
        Find numeric counts in different phase locations and later array entries
        """
        row = ("grain_count", "eq", "343")
        rows, conditions, errors = parse_conditions(condition_query(row))
        self.assertEqual(errors, [])
        data = {"phase": [{"orientation": {"grain_count": 10}}, {"orientation": {"grain_count": "343"}}]}
        self.assertTrue(matches_conditions(data, conditions))
        data = {"phase": [{"grain_count": 343, "orientation": {"grain_count": 10}}]}
        self.assertTrue(matches_conditions(data, conditions))

    def test_preset_text_keys_accept_case_variants_alongside_legacy_keys(self):
        """
        Search case variants without changing the original legacy key spelling
        """
        example = deepcopy(self.example)
        orientation = example["phase"][0]["orientation"]
        orientation["Texture_Type"] = orientation.pop("texture_type")
        for field, expected in (("texture_type", True), ("Texture_Type", True)):
            with self.subTest(field=field):
                rows, conditions, errors = parse_conditions(condition_query((field, "exact", "goss")))
                self.assertEqual(errors, [])
                self.assertEqual(matches_conditions(example, conditions), expected)

    def test_presets_enforce_numeric_and_text_comparisons(self):
        """
        Prevent crafted URLs from bypassing the types used by the preset menu
        """
        for field, operation, value in self.example_rows:
            invalid_operation = "contains" if operation == "eq" else "gt"
            with self.subTest(field=field):
                rows, conditions, errors = parse_conditions(condition_query((field, invalid_operation, "2")))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
                self.assertNotIn("Choose a valid data field", rows[0]["error"])

    def test_parameter_presets_reject_exact_and_numeric_comparisons(self):
        """
        Restrict parameter objects to word searches without representation equality
        """
        for field in ("elastic_parameters", "plastic_parameters"):
            for operation in ("exact", "eq", "gt", "gte", "lt", "lte", "between"):
                upper = "2" if operation == "between" else ""
                with self.subTest(field=field, operation=operation):
                    rows, conditions, errors = parse_conditions(condition_query(
                        ("texture_type", "exact", "goss"),
                        (field, operation, "1", upper),
                    ))
                    self.assertTrue(errors)
                    self.assertEqual(conditions, [])
                    self.assertEqual(rows[1]["operator"], operation)
                    self.assertEqual(rows[1]["value"], "1")
                    self.assertIn("Choose Contains words", rows[1]["error"])
                    self.assertNotIn("Equals text", rows[1]["error"])

    def test_legacy_tokens_do_not_become_aliases_for_different_scientific_fields(self):
        """
        Retain old named key meanings instead of remapping them to new concepts
        """
        example = self.example
        cases = (
            ("Hash_Orientation", "exact", "0abb1"),
            ("Element_Number", "eq", "2744"),
            ("Grain_Number", "eq", "343"),
            ("Material_parameters", "contains", "C11 170000"),
            ("Load_Type", "exact", "force"),
            ("Stress_Type", "exact", "static"),
        )
        for row in cases:
            with self.subTest(field=row[0]):
                rows, conditions, errors = parse_conditions(condition_query(row))
                self.assertEqual(errors, [])
                self.assertFalse(matches_conditions(example, conditions))


class RecursivePresetSearchTests(TestCase):
    """
    Protect normalized preset searches without broadening saved legacy selectors
    """

    def matches(self, data, *rows):
        """
        Evaluate preset rows through the public validation and matching interface

        Parameters
        ----------
        data : object
            JSON object under test.
        *rows : tuple
            Submitted field, operator, value, and optional upper bound.

        Returns
        -------
        bool
            Whether the data satisfies every submitted condition.
        """
        form_rows, conditions, errors = parse_conditions(condition_query(*rows))
        self.assertEqual(errors, [])
        return matches_conditions(data, conditions)

    def test_text_presets_find_normalized_keys_inside_arbitrary_dicts_and_lists(self):
        """
        Find complete normalized field names independently of their schema depth
        """
        for field in ("texture_type", "lattice_structure", "orientation_identifier",
                      "discretization_type", "elastic_model_name", "plastic_model_name"):
            for key in (field, field.upper(), field.replace("_", "-"),
                        " \t" + field.replace("_", " ") + "\n"):
                with self.subTest(field=field, key=key):
                    data = {"wrapper": [{"details": [{key: "Straße texture"}]}]}
                    self.assertTrue(self.matches(data, (field, "exact", "STRASSE TEXTURE")))
                    self.assertFalse(self.matches({key + "_extra": "Straße texture"},
                                                  (field, "exact", "STRASSE TEXTURE")))

    def test_text_presets_only_match_string_scalars_and_all_requested_words(self):
        """
        Exclude serialized containers and numeric coercion from text comparisons
        """
        for value in (150, True, None, {"description": "random"}, {"random": "texture"}):
            for operation, query in (("contains", "random"), ("exact", str(value))):
                with self.subTest(value=value, operation=operation):
                    self.assertFalse(self.matches({"texture_type": value},
                                                  ("texture_type", operation, query)))
        data = {"one": {"texture_type": "random"}, "two": {"TEXTURE-TYPE": ["copper"]}}
        self.assertTrue(self.matches(data, ("texture_type", "contains", "COPPER random")))
        self.assertFalse(self.matches(data, ("texture_type", "contains", "random absent")))
        self.assertFalse(self.matches(data, ("texture_type", "exact", "random copper")))
        self.assertFalse(self.matches({"texture_type": "random", "title": "copper"},
                                      ("texture_type", "contains", "random copper")))

    def test_count_presets_accept_only_named_counts_and_explicit_grain_number_alias(self):
        """
        Match numeric count aliases without conflating grain identifiers or sizes
        """
        for key in ("grain_count", "Grain-Count", "grain number", "GRAIN_NUMBER"):
            with self.subTest(key=key):
                self.assertTrue(self.matches({"nested": [{key: "343"}]},
                                             ("grain_count", "eq", "343")))
        for key in ("grain_id", "grain_size", "grain_count_extra", "grain", "grain_numbering"):
            with self.subTest(key=key):
                self.assertFalse(self.matches({key: 343}, ("grain_count", "eq", "343")))
        for field in ("grain_count", "discretization_count"):
            for value in (True, False, "343 grains", None, "NaN", {"value": 343}):
                with self.subTest(field=field, value=value):
                    self.assertFalse(self.matches({field: value}, (field, "gte", "0")))
            self.assertTrue(self.matches({"nested": [{field.upper(): [1, "343", 1000]}]},
                                         (field, "between", "300", "400")))
            self.assertFalse(self.matches({field: [1, 1000]}, (field, "between", "300", "400")))

    def test_loading_presets_require_a_mechanical_boundary_condition_ancestor(self):
        """
        Restrict loading matches to mechanical branches even within nested wrappers
        """
        for field, value in (("loading_type", "force"), ("loading_mode", "static")):
            row = (field, "exact", value)
            with self.subTest(field=field):
                self.assertTrue(self.matches({"simulation": [{"Mechanical BC": [
                    {"deep": [{field.upper().replace("_", "-"): value}]}]}]}, row))
                for data in (
                    {field: value},
                    {"thermal_BC": [{field: value}]},
                    {"mechanical_BC_extra": [{field: value}]},
                    {"mechanical_BC": [{"THERMAL-BC": {"deep": {field: value}}}]},
                    {"thermal_BC": {"mechanical_BC": {field: value}}},
                ):
                    with self.subTest(data=data):
                        self.assertFalse(self.matches(data, row))

    def test_boolean_preset_matches_json_booleans_without_integer_or_text_coercion(self):
        """
        Keep continuity comparisons strict for both true and false
        """
        self.assertEqual(get_field_operators("RVE_continuity"), ("is",))
        for value, query in ((True, "true"), (False, "false")):
            with self.subTest(value=value):
                row = ("RVE_continuity", "is", query)
                self.assertTrue(self.matches({"nested": [{"rve-continuity": value}]}, row))
                for invalid in (not value, int(value), str(value), query, None, {"value": value}):
                    with self.subTest(invalid=invalid):
                        self.assertFalse(self.matches({"RVE_continuity": invalid}, row))

    def test_boolean_validation_preserves_invalid_intent_and_rejects_other_operators(self):
        """
        Reject loose boolean spellings without silently dropping valid conditions
        """
        for operation, value in (("is", "1"), ("is", "0"), ("is", "yes"),
                                 ("is", "TRUE"), ("contains", "true"),
                                 ("exact", "true"), ("eq", "1"), ("is", "")):
            with self.subTest(operation=operation, value=value):
                rows, conditions, errors = parse_conditions(condition_query(
                    ("texture_type", "exact", "random"),
                    ("RVE_continuity", operation, value),
                ))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
                self.assertEqual(rows[1]["value"], value)
                self.assertEqual(rows[1]["operator"], operation)

    def test_temperature_units_are_converted_to_kelvin_for_every_numeric_operator(self):
        """
        Compare equivalent temperatures in Kelvin regardless of supported stored units
        """
        for unit, value in (("Kelvin", "298.15"), ("K", 298.15),
                            ("Celsius", 25), ("C", "25"), ("°C", 25),
                            ("Fahrenheit", 77), ("F", "77"), ("°F", 77)):
            data = {"global_temperature": value, "units": {"Temperature": unit}}
            for operation, lower, upper, expected in (
                ("eq", "298.15", "", True), ("gt", "298.15", "", False),
                ("gte", "298.15", "", True), ("lt", "298.15", "", False),
                ("lte", "298.15", "", True), ("between", "298", "299", True),
                ("between", "299", "300", False),
            ):
                with self.subTest(unit=unit, operation=operation, lower=lower):
                    self.assertEqual(self.matches(data, ("global_temperature", operation, lower, upper)), expected)

    def test_temperature_units_follow_the_nearest_ancestor_not_a_sibling_phase(self):
        """
        Apply local temperature units while preventing unrelated unit leakage
        """
        data = {"units": {"Temperature": "K"}, "phase": [
            {"units": {"Temperature": "C"}, "state": {"Global-Temperature": 25}},
            {"state": {"global_temperature": 30}},
        ]}
        self.assertTrue(self.matches(data, ("global_temperature", "eq", "298.15")))
        self.assertTrue(self.matches(data, ("global_temperature", "eq", "30")))
        self.assertFalse(self.matches(data, ("global_temperature", "eq", "303.15")))
        self.assertFalse(self.matches({"global_temperature": 25,
                                      "phase": [{"units": {"Temperature": "C"}}]},
                                     ("global_temperature", "eq", "298.15")))
        self.assertFalse(self.matches({"phase": [
            {"units": {"Temperature": "C"}}, {"global_temperature": 25}]},
            ("global_temperature", "eq", "298.15")))
        self.assertFalse(self.matches({"units": {"Temperature": "C"}, "phase": [
            {"units": {"Temperature": "unknown"}, "global_temperature": 25}]},
            ("global_temperature", "eq", "298.15")))
        self.assertTrue(self.matches({"units": {"Temperature": "C"}, "phase": [
            {"units": {"Stress": "MPa"}, "global_temperature": 25}]},
            ("global_temperature", "eq", "298.15")))

    def test_temperatures_with_missing_unknown_or_nonfinite_units_values_do_not_match(self):
        """
        Avoid guessing units or coercing invalid numeric temperature candidates
        """
        for unit in (None, "", "Rankine", "MPa", 1, {"name": "K"}):
            with self.subTest(unit=unit):
                self.assertFalse(self.matches({"global_temperature": 298,
                                              "units": {"Temperature": unit}},
                                             ("global_temperature", "eq", "298")))
        self.assertFalse(self.matches({"global_temperature": 298},
                                      ("global_temperature", "eq", "298")))
        for value in (True, False, None, "NaN", "Infinity", "25 °C", {"value": 25}):
            with self.subTest(value=value):
                self.assertFalse(self.matches({"global_temperature": value,
                                              "units": {"Temperature": "C"}},
                                             ("global_temperature", "gte", "0")))

    def test_temperature_input_and_stored_values_reject_below_absolute_zero(self):
        """
        Keep both submitted Kelvin bounds and converted data physically valid
        """
        for row in (("global_temperature", "gte", "-0.01"),
                    ("global_temperature", "between", "-1", "2"),
                    ("global_temperature", "between", "0", "-1")):
            with self.subTest(row=row):
                rows, conditions, errors = parse_conditions(condition_query(row))
                self.assertTrue(errors)
                self.assertEqual(conditions, [])
        for unit, value in (("K", "-0.01"), ("C", "-273.16"), ("F", "-459.68")):
            with self.subTest(unit=unit):
                self.assertFalse(self.matches({"global_temperature": value,
                                              "units": {"Temperature": unit}},
                                             ("global_temperature", "lt", "1")))
        for unit, value in (("K", 0), ("C", "-273.15"), ("F", "-459.67")):
            with self.subTest(unit=unit):
                self.assertTrue(self.matches({"global_temperature": value,
                                             "units": {"Temperature": unit}},
                                            ("global_temperature", "eq", "0")))

    def test_temperature_conversion_keeps_precision_and_handles_huge_finite_numbers(self):
        """
        Avoid decimal rounding collisions and overflow for finite stored temperatures
        """
        data = {"global_temperature": "0.00000000000000000000000000001",
                "units": {"Temperature": "C"}}
        self.assertFalse(self.matches(data, ("global_temperature", "eq", "273.15")))
        self.assertTrue(self.matches(data, ("global_temperature", "gt", "273.15")))
        for unit in ("K", "C", "F"):
            with self.subTest(unit=unit):
                data = {"global_temperature": "1e1000000", "units": {"Temperature": unit}}
                self.assertTrue(self.matches(data, ("global_temperature", "gt", "1e999999")))

    def test_saved_parameter_tokens_keep_exact_paths_and_container_word_matching(self):
        """
        Retain old parameter URLs without turning them into recursive new presets
        """
        for field in ("elastic_parameters", "plastic_parameters"):
            row = (field, "contains", "C11 170000")
            data = {"phase": [{"constitutive_model": {field: {"C11": 170000}}}]}
            with self.subTest(field=field):
                self.assertTrue(self.matches(data, row))
                self.assertFalse(self.matches({"unrelated": data}, row))
                self.assertFalse(self.matches({field: {"C11": 170000}}, row))

    def test_legacy_paths_do_not_gain_normalization_aliases_or_temperature_conversion(self):
        """
        Keep literal saved paths independent of normalized presets and Kelvin conversion
        """
        data = {"phase": {"Texture-Type": "random", "grain_number": 343},
                "global_temperature": 25, "units": {"Temperature": "C"}}
        self.assertFalse(self.matches(data, ('["phase","texture_type"]', "exact", "random")))
        self.assertFalse(self.matches(data, ('["phase","grain_count"]', "eq", "343")))
        self.assertTrue(self.matches(data, ('["global_temperature"]', "eq", "25")))
        self.assertFalse(self.matches(data, ('["global_temperature"]', "eq", "298.15")))

    def test_recursive_presets_keep_the_existing_dictionary_depth_limit(self):
        """
        Match the supported boundary but stop recursive key discovery beyond it
        """
        data = {"texture_type": "random"}
        for index in range(31):
            data = {"nested": data}
        row = ("texture_type", "exact", "random")
        self.assertTrue(self.matches(data, row))
        self.assertFalse(self.matches({"nested": data}, row))


class AdvancedSearchMatchingTests(TestCase):
    """
    Match exact leaf paths without mixing objects or numeric bounds
    """

    def matches(self, data, *rows):
        """
        Match data through the public parser and evaluator together

        Parameters
        ----------
        data : object
            JSON value to evaluate.
        *rows : tuple
            Serialized condition rows.

        Returns
        -------
        bool
            Whether every validated row matches the data.
        """
        form_rows, conditions, errors = parse_conditions(condition_query(*rows))
        self.assertEqual(errors, [])
        return matches_conditions(data, conditions)

    def test_contains_requires_every_word_only_at_the_selected_path(self):
        """
        Ignore repeated keys elsewhere while allowing words across array values
        """
        row = ('["phase","name"]', "contains", "steel α")
        self.assertTrue(self.matches({"phase": [{"name": "STEEL"}, {"name": "α phase"}]}, row))
        self.assertFalse(self.matches({"phase": {"name": "steel"}, "other": {"name": "α"}}, row))
        self.assertFalse(self.matches({"phase": {"child": {"name": "steel α"}}}, row))

    def test_exact_matches_one_scalar_with_unicode_casefold(self):
        """
        Prevent substring and combined array matches for exact text conditions
        """
        row = ('["keywords"]', "exact", "STRASSE")
        self.assertTrue(self.matches({"keywords": ["Straße", "steel"]}, row))
        self.assertFalse(self.matches({"keywords": ["Straße alloy"]}, row))
        self.assertFalse(self.matches({"keywords": ["Stra", "sse"]}, row))

    def test_selected_container_does_not_search_arbitrary_descendants(self):
        """
        Require the complete path of a scalar field
        """
        self.assertFalse(self.matches({"phase": {"name": "steel"}}, ('["phase"]', "contains", "steel")))

    def test_numeric_operators_compare_values_not_lexical_order(self):
        """
        Preserve strict and inclusive numeric boundaries across data types
        """
        cases = [
            ("eq", "2e0", 2, True), ("eq", "2", "2.00", True),
            ("gt", "2", "10", True), ("gt", "2", 2, False),
            ("gte", "2", 2, True), ("gte", "2", 1.99, False),
            ("lt", "2", -1, True), ("lt", "2", 2, False),
            ("lte", "2", "2", True), ("lte", "2", 10, False),
            ("eq", "0.10000000000000000000000000001", "0.10000000000000000000000000002", False),
            ("gt", "9007199254740992", 9007199254740993, True),
        ]
        for operator, query, value, expected in cases:
            with self.subTest(operator=operator, query=query, value=value):
                self.assertEqual(self.matches({"number": value}, ('["number"]', operator, query)), expected)

    def test_numeric_conditions_ignore_booleans_and_nonfinite_values(self):
        """
        Avoid treating booleans as integers or special values as numbers
        """
        for value in (True, False, None, "NaN", "Infinity", float("inf"), float("nan"), "1_000", "1 GPa"):
            with self.subTest(value=value):
                self.assertFalse(self.matches({"number": value}, ('["number"]', "gte", "0")))

    def test_between_requires_one_array_element_within_both_bounds(self):
        """
        Prevent separate small and large values from satisfying a range
        """
        row = ('["result","stress"]', "between", "2", "8")
        self.assertFalse(self.matches({"result": [{"stress": 1}, {"stress": 9}]}, row))
        self.assertTrue(self.matches({"result": [{"stress": [1, 2, 9]}]}, row))
        self.assertTrue(self.matches({"result": {"stress": [["8"]]}}, row))

    def test_multiple_conditions_are_conjoined(self):
        """
        Require all rows rather than accepting any matching row
        """
        rows = (('["phase"]', "exact", "steel"), ('["count"]', "gt", "5"))
        self.assertTrue(self.matches({"phase": "steel", "count": 6}, *rows))
        self.assertFalse(self.matches({"phase": "steel", "count": 5}, *rows))
        self.assertFalse(self.matches({"phase": "copper", "count": 6}, *rows))

    def test_missing_and_empty_values_do_not_match(self):
        """
        Treat absent or empty fields as no scalar candidates
        """
        for data in ({}, {"phase": None}, {"phase": []}, {"phase": {}}, {"phase": ""}):
            with self.subTest(data=data):
                self.assertFalse(self.matches(data, ('["phase"]', "contains", "steel")))

    def test_numeric_dictionary_keys_are_not_array_indices(self):
        """
        Preserve literal dictionary keys while refusing positional array paths
        """
        row = ('["phase","0"]', "exact", "steel")
        self.assertTrue(self.matches({"phase": [{"0": "steel"}]}, row))
        self.assertFalse(self.matches({"phase": ["steel"]}, row))

    def test_maximum_supported_dictionary_depth_still_matches(self):
        """
        Keep the supported nesting boundary inclusive
        """
        data = 2
        for index in range(32):
            data = {"key": data}
        self.assertTrue(self.matches(data, (json.dumps(["key"] * 32), "eq", "2")))

    def test_all_fixed_fields_match_at_the_root_and_inside_nested_arrays(self):
        """
        Find each Ronak key independently of its enclosing JSON structure
        """
        cases = (
            ("Hash_Orientation", "exact", "target"),
            ("Texture_Type", "exact", "target"),
            ("Element_Number", "eq", "150"),
            ("Grain_Number", "eq", "150"),
            ("Material_parameters", "exact", "target"),
            ("Load_Type", "exact", "target"),
            ("Stress_Type", "exact", "target"),
            ("Load_Descriptor", "exact", "target"),
            ("Hash_load", "exact", "target"),
            ("Scaling_Factor", "eq", "150"),
            ("Max_Total_Strain", "eq", "150"),
        )
        for field, operation, value in cases:
            for data in ({field: value.upper()}, {"simulation": [{"phase": [{field: value.upper()}]}]}):
                with self.subTest(field=field, data=data):
                    self.assertTrue(self.matches(data, (field, operation, value)))

    def test_named_field_keys_ignore_case_but_not_suffixes_or_whitespace(self):
        """
        Match a complete stored key without treating it as a substring
        """
        row = ("Grain_Number", "gt", "100")
        self.assertTrue(self.matches({"phase": [{"gRaIn_nUmBeR": 150}]}, row))
        for data in ({"Grain_Number_Extra": 150}, {" Grain_Number ": 150}, {"Grain_Number": 50, "Other": 150}):
            with self.subTest(data=data):
                self.assertFalse(self.matches(data, row))

    def test_named_numeric_fields_keep_numeric_operators_and_precision(self):
        """
        Compare named field scalars numerically rather than as ordered text
        """
        cases = (
            ("eq", "2", "2.00", True), ("eq", "2", 3, False),
            ("gt", "2", "10", True), ("gt", "2", 2, False),
            ("gte", "2", 2, True), ("gte", "2", 1, False),
            ("lt", "2", -1, True), ("lt", "2", 2, False),
            ("lte", "2", 2, True), ("lte", "2", 10, False),
            ("gt", "9007199254740992", 9007199254740993, True),
        )
        for operation, expected, value, matches in cases:
            with self.subTest(operation=operation, value=value):
                self.assertEqual(self.matches({"phase": [{"Grain_Number": value}]},
                                              ("Grain_Number", operation, expected)), matches)

    def test_named_numeric_fields_ignore_boolean_null_and_nonnumeric_values(self):
        """
        Keep invalid numeric candidates from being coerced into a match
        """
        values = (True, False, None, "NaN", "Infinity", float("nan"), float("inf"), "1_000", "150 GPa", {"value": 150})
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(self.matches({"Grain_Number": value}, ("Grain_Number", "gte", "0")))

    def test_named_missing_and_null_fields_do_not_match_text(self):
        """
        Avoid turning absent or null named fields into textual candidates
        """
        for data in ({}, {"Texture_Type": None}, {"Texture_Type": ""}):
            with self.subTest(data=data):
                self.assertFalse(self.matches(data, ("Texture_Type", "contains", "none")))

    def test_all_allowed_named_field_operators_match_values_of_their_type(self):
        """
        Keep every permitted comparison usable for scalar and array fields

        Array comparisons retain whole value text and individual numeric values.
        """
        numeric_fields = ("Grain_Number", "Element_Number", "Scaling_Factor", "Max_Total_Strain", "Material_parameters")
        numeric_rows = (
            ("eq", "5", ""), ("gt", "4", ""), ("gte", "5", ""),
            ("lt", "6", ""), ("lte", "5", ""), ("between", "4", "6"),
        )
        for field in numeric_fields:
            value = [1, 5, 9] if field == "Material_parameters" else 5
            for operation, lower, upper in numeric_rows:
                with self.subTest(field=field, operation=operation):
                    self.assertTrue(self.matches({field: value}, (field, operation, lower, upper)))
        text_fields = ("Hash_Orientation", "Texture_Type", "Load_Type", "Stress_Type", "Load_Descriptor", "Hash_load")
        for field in text_fields:
            for operation, value in (("contains", "target"), ("exact", "target value")):
                with self.subTest(field=field, operation=operation):
                    self.assertTrue(self.matches({field: "TARGET VALUE"}, (field, operation, value)))

    def test_legacy_paths_keep_operators_that_are_invalid_for_the_named_field(self):
        """
        Preserve saved explicit path semantics independently of the new types

        Only named catalog tokens use the field specific operator restrictions.
        """
        self.assertTrue(self.matches({"phase": {"Grain_Number": 150}},
                                     ('["phase","Grain_Number"]', "contains", "15")))
        self.assertTrue(self.matches({"Texture_Type": "150"}, ('["Texture_Type"]', "gt", "100")))

    def test_material_parameters_matches_whole_array_and_object_text(self):
        """
        Preserve Ronak text matching across complete material parameter values
        """
        self.assertTrue(self.matches({"phase": [{"Material_parameters": [1, 2, 3]}]},
                                     ("Material_parameters", "contains", "[1, 2")))
        self.assertTrue(self.matches({"Material_parameters": {"Elastic": [210000, 0.3]}},
                                     ("Material_parameters", "contains", "elastic 210000")))
        self.assertTrue(self.matches({"Material_parameters": [1, 2]},
                                     ("Material_parameters", "exact", "[1, 2]")))

    def test_named_ranges_require_one_array_scalar_within_both_bounds(self):
        """
        Evaluate numeric array entries without mixing bounds between values
        """
        row = ("Material_parameters", "between", "2", "8")
        self.assertFalse(self.matches({"Material_parameters": [1, 9]}, row))
        self.assertTrue(self.matches({"Material_parameters": [1, ["2"], 9]}, row))
        self.assertTrue(self.matches({"phase": [{"Material_parameters": 8}]}, row))
        self.assertFalse(self.matches({"phase": [{"Material_parameters": 1}, {"Material_parameters": 9}]}, row))

    def test_named_conditions_are_combined_with_and(self):
        """
        Require every fixed field condition to match the same data object
        """
        rows = (("Grain_Number", "gt", "100"), ("Texture_Type", "exact", "random"))
        self.assertTrue(self.matches({"Grain_Number": 150, "phase": {"Texture_Type": "random"}}, *rows))
        self.assertFalse(self.matches({"Grain_Number": 150, "Texture_Type": "aligned"}, *rows))

    def test_legacy_paths_remain_precise_when_the_same_named_field_exists_elsewhere(self):
        """
        Keep saved explicit paths separate from recursive named field matching
        """
        data = {"phase": [{"Grain_Number": 50}], "other": {"Grain_Number": 150}}
        self.assertTrue(self.matches(data, ("Grain_Number", "gt", "100")))
        self.assertFalse(self.matches(data, ('["phase","Grain_Number"]', "gt", "100")))
        self.assertFalse(self.matches({"phase": {"grain_number": 150}},
                                      ('["phase","Grain_Number"]', "gt", "100")))

    def test_named_field_traversal_stops_after_the_supported_depth(self):
        """
        Keep the depth boundary inclusive without unbounded key discovery
        """
        data = {"Grain_Number": 150}
        for index in range(31):
            data = {"nested": data}
        self.assertTrue(self.matches(data, ("Grain_Number", "gt", "100")))
        self.assertFalse(self.matches({"nested": data}, ("Grain_Number", "gt", "100")))

    def test_named_contains_treats_regex_punctuation_as_literal_text(self):
        """
        Keep search values literal even when they resemble regular expressions
        """
        row = ("Load_Descriptor", "contains", ".*")
        self.assertFalse(self.matches({"Load_Descriptor": "tension"}, row))
        self.assertTrue(self.matches({"Load_Descriptor": "literal .* pattern"}, row))

    def test_legacy_path_matching_stops_after_the_supported_depth(self):
        """
        Keep legacy path evaluation bounded when arrays are deeply nested
        """
        nested = "steel"
        for index in range(40):
            nested = [nested]
        data = {"deep": nested, "phase": "steel"}
        rows, conditions, errors = parse_conditions(condition_query(('["deep"]', "exact", "steel")))
        self.assertEqual(errors, [])
        self.assertFalse(matches_conditions(data, conditions))
