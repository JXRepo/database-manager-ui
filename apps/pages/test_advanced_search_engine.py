import json
from unittest import TestCase

from django.http import QueryDict

from .advanced_search import (
    discover_fields,
    format_field_path,
    matches_conditions,
    parse_conditions,
)


def condition_query(*rows):
    """
    Build repeated form parameters without invoking a view

    Parameters
    ----------
    *rows : tuple
        Field JSON, operator, first value, and optional second value.

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


class AdvancedSearchFieldDiscoveryTests(TestCase):
    """
    Discover precise selectable paths from JSON data
    """

    def test_discovery_traverses_arrays_and_skips_technical_fields(self):
        """
        Expose numeric and textual leaves without metadata paths or indices
        """
        data = {
            "phase": [{"name": "steel", "Grain_Number": 12}, {"name": "copper"}],
            "curve": [[1, 2], [3, 4]],
            "keywords": ["a", "b"],
            "flag": True,
            "$schema": "schema.json",
            " INPUT_PATH ": {"hidden": "path"},
            "nested": {"results_path": "path", "visible": "text"},
            "empty": [],
            "missing": None,
        }
        self.assertEqual(set(discover_fields(data)), {
            ("phase", "name"), ("phase", "Grain_Number"), ("curve",),
            ("keywords",), ("flag",), ("nested", "visible"),
        })

    def test_paths_preserve_punctuation_and_format_readably(self):
        """
        Keep literal dots and slashes as part of dictionary keys
        """
        self.assertEqual(set(discover_fields({"phase.key": {"a/b": 1}})), {("phase.key", "a/b")})
        self.assertEqual(format_field_path(("phase", "Grain_Number")), "phase / Grain_Number")

    def test_discovery_omits_paths_that_cannot_be_submitted(self):
        """
        Avoid presenting overly long or invalid Unicode field keys
        """
        self.assertEqual(set(discover_fields({"x" * 1024: 1, "\ud800": 2, "phase": "steel"})), {("phase",)})

    def test_deep_json_is_bounded_for_discovery_and_matching(self):
        """
        Stop excessive nesting while retaining ordinary fields nearby
        """
        nested = "steel"
        for index in range(40):
            nested = [nested]
        data = {"deep": nested, "phase": "steel"}
        self.assertEqual(set(discover_fields(data)), {("phase",)})
        rows, conditions, errors = parse_conditions(condition_query(('["deep"]', "exact", "steel")))
        self.assertEqual(errors, [])
        self.assertFalse(matches_conditions(data, conditions))
