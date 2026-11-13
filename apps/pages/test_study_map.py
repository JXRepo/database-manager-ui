"""
Verify exact parameter coordinates, complete coverage and native map filtering
"""

from copy import deepcopy
from decimal import Decimal, localcontext
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from .collection_graph import SummaryPreparationBudget, collection_summaries
from .collection_summary import build_collection_summary
from .models import JSONData
from .research_collections import accessible_objects
from .study_map import AXIS_WINDOW, build_map_context, build_map_projection, map_parameters


class MapProjectionTests(SimpleTestCase):
    """
    Keep exact scalar meaning and reject aliases or shapes that require guessing
    """

    def test_original_numeric_text_and_types_survive_without_rounding(self):
        """
        Retain decimal spelling and large integers beyond binary float precision
        """
        original = {"Global temperature": [[" 9.007199254740993001e15 "]],
                    "Discretization count": 9007199254740993, "UNITS": [{"Temperature": ["K"]}]}
        before = deepcopy(original)
        with localcontext() as context:
            context.prec = 4
            projection = build_map_projection(original)
        temperature = projection["fields"]["temperature"]
        count = projection["fields"]["discretization_count"]
        self.assertEqual(temperature["state"], "recorded")
        self.assertEqual(temperature["value"], " 9.007199254740993001e15 ")
        self.assertEqual(temperature["value_type"], "numeric_text")
        self.assertEqual(Decimal(temperature["number"]), Decimal("9007199254740993.001"))
        self.assertEqual(count["value_type"], "int")
        self.assertEqual(Decimal(count["number"]), Decimal("9007199254740993"))
        self.assertEqual(temperature["path"], "global_temperature")
        self.assertEqual(temperature["unit_path"], "units.Temperature")
        self.assertEqual(original, before)

    def test_equal_numeric_spellings_share_coordinates_and_zero_is_valid(self):
        """
        Keep zero and equal decimal values without preserving artificial bins
        """
        identities = []
        for value in ("0", "-0.000", 0, 0.0):
            field = build_map_projection({"global_temperature": value, "units": {"Temperature": "K"},
                                          "discretization_count": value})["fields"]
            self.assertEqual({item["state"] for item in field.values()}, {"recorded"})
            identities.append(field["temperature"]["number"])
        self.assertEqual(set(identities), {"0"})
        first = build_map_projection({"discretization_count": "1.2300"})["fields"]["discretization_count"]
        second = build_map_projection({"discretization_count": "123e-2"})["fields"]["discretization_count"]
        self.assertEqual(first["number"], second["number"])
        self.assertNotEqual(first["value"], second["value"])

    def test_conflicting_aliases_are_ambiguous_at_their_own_parent(self):
        """
        Reject different original types and unit aliases without borrowing nested values
        """
        for extra in (
            {"Global temperature": "300.000"},
            {"units": {"Temperature": "K", "temperature": "C"}},
            {"UNITS": {"Temperature": "C"}},
        ):
            data = {"global_temperature": 300, "discretization_count": 10, "units": {"Temperature": "K"}, **extra}
            projection = build_collection_summary(data)["parameter_map"]
            self.assertEqual(projection["fields"]["temperature"]["state"], "ambiguous")
            self.assertEqual(projection["fields"]["discretization_count"]["state"], "recorded")
        nested = build_map_projection({"unknown": {"global_temperature": 300, "discretization_count": 1},
                                       "phase": [{"orientation": {"grain_count": 20}}]})
        self.assertEqual({item["state"] for item in nested["fields"].values()}, {"missing"})

    def test_equivalent_unit_container_aliases_accept_known_names_and_wrappers(self):
        """
        Recognize equivalent unit containers without changing precise numeric values
        """
        for alias in ({"temperature": "K"}, {"Temperature": ["K"]},
                      [{"TEMPERATURE": [["K"]]}]):
            data = {"global_temperature": "9007199254740993.001", "discretization_count": 10,
                    "units": {"Temperature": "K"}, "UNITS": alias}
            before = deepcopy(data)
            with self.subTest(alias=alias):
                for projection in (build_map_projection(data), build_collection_summary(data)["parameter_map"]):
                    temperature = projection["fields"]["temperature"]
                    self.assertEqual(temperature["state"], "recorded")
                    self.assertEqual(temperature["unit"], "K")
                    self.assertEqual(temperature["value"], "9007199254740993.001")
                    self.assertEqual(temperature["value_type"], "numeric_text")
                self.assertEqual(data, before)

    def test_unit_container_aliases_preserve_unknown_keys_and_exact_scalar_conflicts(self):
        """
        Keep unrelated freeform names and unequal unit values outside normalization
        """
        for first, second in (
            ({"Temperature": "K", "freeform": ["original"]}, {"temperature": "K", "freeform": "original"}),
            ({"Temperature": "K", "freeform": "original"}, {"temperature": "K", "FREEFORM": "original"}),
            ({"Temperature": "K", "Strain": "1"}, {"temperature": "K", "strain": 1}),
            ({"Temperature": "K"}, {"temperature": "K", "TEMPERATURE": "C"}),
        ):
            data = {"global_temperature": 300, "discretization_count": 10, "units": first, "UNITS": second}
            with self.subTest(first=first, second=second):
                self.assertEqual(build_map_projection(data)["fields"]["temperature"]["state"], "ambiguous")
        data = {"global_temperature": "9007199254740993.001", "Global temperature": "9007199254740993.002",
                "discretization_count": 10, "units": {"Temperature": "K"}}
        self.assertEqual(build_collection_summary(data)["parameter_map"]["fields"]["temperature"]["state"], "ambiguous")

    def test_missing_invalid_and_unsupported_values_remain_distinct(self):
        """
        Distinguish empty fields from unsupported scalar shapes and unit names
        """
        for value in (None, "", "  ", [], {}, [[None]]):
            projection = build_map_projection({"global_temperature": 0, "units": {"Temperature": value}})
            self.assertEqual(projection["fields"]["temperature"]["state"], "missing")
        for value in (False, True, [1, 2], "nan", "infinity", float("inf"), {"value": 1}, "9" * 513):
            projection = build_map_projection({"discretization_count": value})
            self.assertEqual(projection["fields"]["discretization_count"]["state"], "invalid")
        projection = build_map_projection({"global_temperature": 300, "units": {"Temperature": "joules"}})
        self.assertEqual(projection["fields"]["temperature"]["state"], "unsupported_unit")
        self.assertEqual(projection["fields"]["temperature"]["unit"], "joules")

    def test_projection_is_bounded_and_does_not_retain_arrays(self):
        """
        Exclude curve and arbitrary metadata containers from retained map fields
        """
        data = {"global_temperature": "1e999999", "discretization_count": "1e-999999",
                "units": {"Temperature": "K"}, "stress": {"stress_11": list(range(10000))},
                "unknown": {"secret": "A" * 10000}}
        projection = build_map_projection(data)
        self.assertLess(len(json.dumps(projection)), 1024)
        self.assertNotIn("secret", json.dumps(projection))
        self.assertEqual(projection["fields"]["temperature"]["number"], "1e999999")

    def test_controls_reject_ambiguous_input_and_omit_defaults(self):
        """
        Reject invalid axes, pages and identities before preparing any records
        """
        for query in (
            "map_x=temperature&map_x=temperature", "map_x=grain_count", "map_x=discretization_count",
            "map_y_page=0", "map_x_page=-1", "map_x_page=2147483648", "map_x_page=01",
            "map_unit=K", "map_cell=wrong", "map_row=" + "a" * 64 + "&map_cell=" + "b" * 64,
        ):
            with self.subTest(query=query), self.assertRaises(ValueError):
                map_parameters(QueryDict(query))
        self.assertEqual(map_parameters(QueryDict("map_x=temperature&map_y=discretization_count&map_x_page=1")), {})
        self.assertEqual(map_parameters({"map_x": "discretization_count", "map_y": "temperature"}),
                         {"map_x": "discretization_count", "map_y": "temperature"})


class ParameterMapTests(TestCase):
    """
    Check full accessible counts, native filtering, preparation and cache reads
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create separate viewers so revoked private metadata can be detected
        """
        cls.owner = User.objects.create_user(username="map-owner")
        cls.other = User.objects.create_user(username="map-other")

    def record(self, temperature=300, count=10, unit="K", **changes):
        """
        Store a synthetic scalar record with accurate original JSON size

        Parameters
        ----------
        temperature, count : object, optional
            Deliberately varied recorded map coordinates.
        unit : object, optional
            Explicit temperature unit.
        **changes : object
            Additional or replacing original metadata values.

        Returns
        -------
        JSONData
            Owned synthetic record with a current cached projection.
        """
        data = {"title": "Synthetic parameter map record", "global_temperature": temperature,
                "discretization_count": count, "units": {"Temperature": unit}, **changes}
        return JSONData.objects.create(owner=self.owner, data=data, size_bytes=len(json.dumps(data).encode()))

    def context(self, query="", navigation=None, budget=None, objects=None):
        """
        Build the map from an explicit permission scope

        Parameters
        ----------
        query : str, optional
            Native query arguments.
        navigation : dict or None, optional
            Validated existing pins and workspace state.
        budget : SummaryPreparationBudget or None, optional
            Allowance shared with another summary consumer.
        objects : QuerySet or None, optional
            Access scope override for permission checks.

        Returns
        -------
        dict
            Map grid and native continuation state.
        """
        scope = accessible_objects(self.owner) if objects is None else objects
        return build_map_context(scope, QueryDict(query), base_url="/graph/collections/1/",
                                 navigation_params=navigation, preparation_budget=budget)

    def test_decimal_sorting_counts_and_warm_queries_preserve_full_precision(self):
        """
        Sort large neighboring values exactly while reading only summary projections
        """
        self.record("9007199254740993", "0")
        self.record("9007199254740992", 0)
        self.record("9.007199254740993e15", "-0.00")
        with CaptureQueriesContext(connection) as queries:
            context = self.context()
        self.assertTrue(context["ready"])
        self.assertIsNone(context["member_ids"])
        self.assertEqual([Decimal(value["key"]) for value in context["x_axis"]["values"]],
                         [Decimal("9007199254740992"), Decimal("9007199254740993")])
        self.assertEqual([cell["count"] for cell in context["rows"][0]["cells"]], [1, 2])
        self.assertEqual(context["counts"]["total"], 3)
        self.assertEqual(context["max_count"], 2)
        self.assertEqual([cell["intensity"] for cell in context["rows"][0]["cells"]], [1, 5])
        self.assertTrue(all('"pages_jsondata"."data"' not in query["sql"] for query in queries))
        self.assertTrue(all("summary_raw_bytes" not in query["sql"] for query in queries))

    def test_explicit_unit_spellings_remain_separate_without_conversion(self):
        """
        Keep Kelvin, Celsius and spelling variants in distinct selectable maps
        """
        for unit, value in (("K", 300), ("kelvin", 300), ("C", 26.85), ("F", 80.33)):
            self.record(value, unit=unit)
        self.record(300, unit="joules")
        context = self.context()
        self.assertEqual([unit["label"] for unit in context["units"]], ["C", "F", "K", "kelvin"])
        self.assertEqual(context["counts"]["mapped"], 4)
        self.assertEqual(context["counts"]["selected_unit"], 1)
        self.assertEqual(context["counts"]["other_units"], 3)
        self.assertEqual(context["counts"]["unsupported_unit"], 1)
        self.assertEqual(context["selected_unit"], "C")
        self.assertEqual(context["state"]["map_unit"], context["units"][0]["value"])
        kelvin = next(unit for unit in context["units"] if unit["label"] == "K")
        selected = self.context(urlsplit(kelvin["url"]).query)
        self.assertEqual(selected["selected_unit"], "K")
        self.assertEqual(selected["x_axis"]["label"], "Global temperature (K)")
        self.assertEqual(selected["x_axis"]["values"][0]["label"], "300")

    def test_exclusion_counts_are_explicit_disjoint_and_zero_stays_mapped(self):
        """
        Count each unavailable pair once without inferring missing discretization values
        """
        self.record(0, 0)
        self.record(None, None)
        self.record(False, False)
        self.record(300, 10, **{"Global temperature": 301})
        self.record(300, 10, unit="unknown")
        self.record(300, None, phase=[{"orientation": {"grain_count": 100}}])
        context = self.context()
        self.assertEqual(context["counts"], {"total": 6, "mapped": 1, "selected_unit": 1, "other_units": 0,
                                             "excluded": 5, "ambiguous": 1, "invalid": 1, "missing": 2,
                                             "unsupported_unit": 1})
        self.assertEqual(context["rows"][0]["cells"][0]["count"], 1)
        self.assertEqual(len(context["excluded_reasons"]), 4)

    def test_axis_windows_and_rows_keep_full_counts_and_ordered_pins(self):
        """
        Bound visible cells while preserving full row filters and comparison order
        """
        records = [self.record(index, index) for index in range(11)]
        extra = self.record(10, 0)
        pins = f"{records[-1].pk},{records[0].pk}"
        context = self.context(navigation={"compare": pins, "members_page": "3"})
        self.assertEqual(len(context["x_axis"]["values"]), AXIS_WINDOW)
        self.assertEqual(len(context["rows"]), AXIS_WINDOW)
        self.assertEqual(sum(len(row["cells"]) for row in context["rows"]), 64)
        self.assertEqual(context["rows"][0]["count"], 2)
        self.assertEqual(context["counts"]["selected_unit"], 12)
        row_query = parse_qs(urlsplit(context["rows"][0]["url"]).query)
        self.assertEqual(row_query["compare"], [pins])
        self.assertNotIn("members_page", row_query)
        selected_row = self.context(urlsplit(context["rows"][0]["url"]).query)
        self.assertEqual(set(selected_row["member_ids"]), {records[0].pk, extra.pk})
        self.assertEqual(selected_row["selected_label"], "Discretization count: 0 · Temperature unit: K")
        cell_url = context["rows"][0]["cells"][0]["url"]
        selected_cell = self.context(urlsplit(cell_url).query)
        self.assertEqual(selected_cell["member_ids"], [records[0].pk])
        self.assertEqual(urlsplit(cell_url).fragment, "study-member-browser")
        last = self.context("map_x_page=999&map_y_page=999")
        self.assertEqual(last["state"]["map_x_page"], "2")
        self.assertEqual(last["state"]["map_y_page"], "2")
        self.assertEqual(len(last["rows"]), 3)
        self.assertEqual(len(last["x_axis"]["values"]), 3)

    def test_selection_remains_authoritative_when_scrolling_axis_windows(self):
        """
        Preserve an offscreen populated cell selection while browsing another window
        """
        records = [self.record(index, 0) for index in range(10)]
        first = self.context()
        selected_query = urlsplit(first["rows"][0]["cells"][0]["url"]).query
        selected = self.context(selected_query + "&map_x_page=2")
        self.assertEqual(selected["member_ids"], [records[0].pk])
        self.assertEqual(selected["x_axis"]["page"], 2)
        self.assertTrue(selected["selected_label"])

    def test_invalid_and_stale_choices_never_broaden_the_member_filter(self):
        """
        Empty results on malformed controls, unknown units and deleted coordinates
        """
        record = self.record()
        initial = self.context()
        selected_query = urlsplit(initial["rows"][0]["cells"][0]["url"]).query
        for query in ("map_unit=" + "0" * 64, "map_row=" + "0" * 64,
                      "map_cell=" + "0" * 64, "map_x_page=0", "map_y=temperature"):
            with self.subTest(query=query):
                result = self.context(query, navigation={"compare": str(record.pk)})
                self.assertTrue(result["error"])
                self.assertFalse(result["ready"])
                self.assertEqual(result["member_ids"], [])
                self.assertEqual(result["counts"], {})
                self.assertEqual(parse_qs(urlsplit(result["clear_url"]).query),
                                 {"panel": ["map"], "compare": [str(record.pk)]})
        record.data["global_temperature"] = 301
        record.save(update_fields=["data"])
        stale = self.context(selected_query)
        self.assertIn("cell", stale["error"])
        self.assertEqual(stale["member_ids"], [])

    def test_axis_swap_changes_coordinates_and_clears_cell_and_page_state(self):
        """
        Keep unit and pins when switching the two explicitly supported axes
        """
        record = self.record(300, 20)
        initial = self.context(navigation={"compare": str(record.pk)})
        query = urlsplit(initial["rows"][0]["cells"][0]["url"]).query
        selected = self.context(query, navigation={"compare": str(record.pk)})
        swap_arguments = parse_qs(urlsplit(selected["swap_url"]).query)
        self.assertNotIn("map_cell", swap_arguments)
        self.assertNotIn("map_x_page", swap_arguments)
        self.assertEqual(swap_arguments["compare"], [str(record.pk)])
        swapped = self.context(urlsplit(selected["swap_url"]).query)
        self.assertEqual(swapped["x_axis"]["label"], "Discretization count")
        self.assertEqual(swapped["y_axis"]["label"], "Global temperature (K)")
        self.assertIn("Global temperature (K): 300", swapped["rows"][0]["cells"][0]["title"])
        self.assertEqual(swapped["rows"][0]["label"], "300")
        self.assertEqual(swapped["x_axis"]["values"][0]["label"], "20")

    def test_empty_collection_is_ready_and_stale_unit_returns_an_explicit_error(self):
        """
        Distinguish a truly empty accessible collection from a stale saved selection
        """
        context = self.context()
        self.assertTrue(context["ready"])
        self.assertEqual(context["counts"]["total"], 0)
        self.assertIsNone(context["member_ids"])
        self.assertEqual(context["rows"], [])
        stale = self.context("map_unit=" + "a" * 64)
        self.assertTrue(stale["error"])
        self.assertEqual(stale["member_ids"], [])

    def test_shared_preparation_budget_never_exposes_partial_counts(self):
        """
        Prepare only the remaining allowed record before reporting honest progress
        """
        first, second = self.record(300), self.record(301)
        JSONData.objects.filter(pk__in=[first.pk, second.pk]).update(collection_summary=None)
        budget = SummaryPreparationBudget(checked_count=24)
        context = self.context(budget=budget)
        self.assertFalse(context["ready"])
        self.assertEqual(context["preparation"], {"ready_count": 1, "total_count": 2, "requires_admin": False})
        self.assertEqual(context["counts"], {})
        self.assertEqual(context["rows"], [])
        self.assertEqual(context["member_ids"], [])
        self.assertEqual(budget.checked_count, 25)
        self.assertTrue(self.context()["ready"])

    def test_legacy_comparison_summaries_upgrade_to_map_version(self):
        """
        Use the existing bounded summary preparation for legacy comparison records
        """
        record = self.record()
        legacy = deepcopy(record.collection_summary)
        legacy["summary_version"] = 2
        legacy.pop("parameter_map")
        JSONData.objects.filter(pk=record.pk).update(collection_summary=legacy)
        context = self.context()
        self.assertTrue(context["ready"])
        record.refresh_from_db()
        self.assertEqual(record.collection_summary["summary_version"], 3)
        self.assertEqual(record.collection_summary["parameter_map"]["version"], 1)

    def test_actual_json_bytes_and_unknown_sizes_require_operator_preparation(self):
        """
        Check actual database bytes before reading a falsely undersized record
        """
        record = self.record(unknown="X" * 1000)
        JSONData.objects.filter(pk=record.pk).update(collection_summary=None, size_bytes=1)
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_BYTES", 512):
            with CaptureQueriesContext(connection) as queries:
                context = self.context()
        self.assertFalse(context["ready"])
        self.assertTrue(context["preparation"]["requires_admin"])
        self.assertEqual(context["counts"], {})
        self.assertTrue(all(not query["sql"].startswith('SELECT "pages_jsondata"."id", "pages_jsondata"."data"')
                            for query in queries))
        JSONData.objects.filter(pk=record.pk).update(size_bytes=0)
        with patch("apps.pages.collection_graph.build_collection_summary") as builder:
            self.assertTrue(self.context()["preparation"]["requires_admin"])
            builder.assert_not_called()

    def test_permissions_are_applied_before_cache_reads_and_rechecked_after_preparation(self):
        """
        Hide inaccessible objects and reject a scope changed while assembling the map
        """
        record = self.record()
        record.shared_users.add(self.other)
        scope = accessible_objects(self.other)
        self.assertEqual(self.context(objects=scope)["counts"]["total"], 1)

        def revoke_after_summaries(objects, **options):
            """
            Revoke the private share after summary reads to exercise the fresh access query

            Parameters
            ----------
            objects : QuerySet
                Initial permission scope.
            **options : object
                Existing preparation arguments.

            Yields
            ------
            dict
                Previously accessible scalar summary.
            """
            yield from collection_summaries(objects, **options)
            record.shared_users.clear()

        with patch("apps.pages.collection_graph.collection_summaries", side_effect=revoke_after_summaries):
            changed = self.context(objects=scope)
        self.assertIn("changed", changed["error"])
        self.assertEqual(changed["member_ids"], [])
        self.assertEqual(changed["counts"], {})
        self.assertEqual(self.context(objects=scope)["counts"]["total"], 0)
