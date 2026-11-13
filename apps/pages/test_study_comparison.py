"""
Check bounded comparisons of recorded simulation metadata without modifying data
"""

from copy import deepcopy
import csv
from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.http import QueryDict
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .collection_summary import build_collection_summary
from .models import JSONData, ResearchCollection
from .research_collections import accessible_objects
from .study_comparison import MAX_PROJECTION_BYTES, SUMMARY_VERSION, outdated_summary_query, parse_comparison_ids


class StudyComparisonTests(TestCase):
    """
    Exercise recorded values, access boundaries, cache preparation and CSV exports
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create two compatible schema shapes with deliberately different recorded units
        """
        cls.owner = User.objects.create_user(username="study-owner")
        cls.other = User.objects.create_user(username="study-other")
        cls.metadata = {
            "identifier": "study-first", "title": "Copper baseline", "software": "DAMASK",
            "software_version": "3.0", "RVE_size": [1, 2, 3], "RVE_continuity": False,
            "discretization_type": "Structured", "discretization_count": 0,
            "global_temperature": 300, "units": {"Length": "mm", "Temperature": "K", "Stress": "MPa", "Strain": 1},
            "phase": [{"phase_name": "Copper", "lattice_structure": "FCC",
                       "orientation": {"texture_type": "Goss", "grain_count": 343},
                       "constitutive_model": {"elastic_model_name": "Elastic", "plastic_model_name": "Plastic"}}],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "static"}],
            "stress": {"stress_11": [0, 1.23456789]}, "total_strain": {"strain_11": [0, 0.1]},
        }
        cls.first = JSONData.objects.create(owner=cls.owner, data=cls.metadata,
                                           size_bytes=len(json.dumps(cls.metadata).encode()))
        second = deepcopy(cls.metadata)
        second.update(identifier="study-second", title="Copper variant", global_temperature=26.85)
        second["units"]["Temperature"] = "C"
        cls.second = JSONData.objects.create(owner=cls.owner, data=second,
                                            size_bytes=len(json.dumps(second).encode()))
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "SECRET hidden simulation"})
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Study")
        cls.collection.members.add(cls.first, cls.second, cls.hidden)

    def context(self, query):
        """
        Compare only records the signed in collection owner currently can access

        Parameters
        ----------
        query : str
            Encoded comparison selection and display preferences.

        Returns
        -------
        dict
            Safe comparison context.
        """
        from .study_comparison import build_comparison_context

        return build_comparison_context(
            accessible_objects(self.owner).filter(research_collections=self.collection),
            QueryDict(query), base_url=reverse("collection_detail", args=[self.collection.pk]),
        )

    def test_summary_contains_bounded_domain_projection_without_raw_arrays(self):
        """
        Preserve zero, false, phase context and available components in the scalar cache
        """
        original = deepcopy(self.metadata)
        summary = build_collection_summary(original)
        self.assertIn("comparison", summary)
        self.assertEqual(summary["summary_version"], SUMMARY_VERSION)
        fields = summary["comparison"]["fields"]
        self.assertEqual(fields["rve_continuity"]["entries"][0]["value"], "false")
        self.assertEqual(fields["discretization_count"]["entries"][0]["value"], "0")
        self.assertEqual(fields["texture"]["entries"][0]["context"], "Phase 1")
        self.assertEqual(fields["texture"]["entries"][0]["path"], "phase[0].orientation.texture_type")
        self.assertNotIn("1.23456789", json.dumps(summary["comparison"]))
        self.assertEqual(original, self.metadata)

    def test_empty_scalar_wrappers_stay_missing_while_zero_and_false_stay_recorded(self):
        """
        Recheck known scalar emptiness after unwrapping without hiding valid zero or false
        """
        for empty in ([None], [""], [[]], [{}]):
            with self.subTest(value=empty):
                data = deepcopy(self.metadata)
                data["discretization_count"] = empty
                cell = build_collection_summary(data)["comparison"]["fields"]["discretization_count"]
                self.assertEqual(cell["state"], "not_supplied")
                self.assertEqual(cell["entries"][0]["value"], "Not supplied")
                self.assertEqual(cell["key"], "")
        data = deepcopy(self.metadata)
        data.update(discretization_count=[0], RVE_continuity=[False])
        fields = build_collection_summary(data)["comparison"]["fields"]
        for key, display in (("discretization_count", "0"), ("rve_continuity", "false")):
            self.assertEqual(fields[key]["state"], "recorded")
            self.assertEqual(fields[key]["entries"][0]["value"], display)

    def test_complete_comparison_preserves_reference_order_and_explicit_units(self):
        """
        Distinguish recorded units without converting temperatures or claiming comparability
        """
        result = self.context(f"compare={self.second.pk},{self.first.pk}&differences=1")
        self.assertTrue(result["ready"])
        self.assertEqual([obj["pk"] for obj in result["objects"]], [self.second.pk, self.first.pk])
        rows = {row["key"]: row for row in result["rows"]}
        self.assertEqual(rows["software"]["status"], "same")
        self.assertEqual(rows["temperature"]["status"], "different")
        self.assertEqual([cell["entries"][0]["value"] for cell in rows["temperature"]["cells"]], ["26.85 C", "300 K"])
        self.assertEqual(rows["temperature"]["cells"][1]["matches_reference"], False)
        self.assertEqual(sum(result["counts"].values()), 16)
        self.assertTrue(result["differences"])

    def test_numeric_text_keeps_original_precision_and_types(self):
        """
        Avoid collapsing distinct high precision metadata through floating point conversion
        """
        cases = (("1.00000000000000001", "1.00000000000000002"),
                 ("9007199254740992.0", "9007199254740993.0"), ("300", 300))
        for first_value, second_value in cases:
            with self.subTest(first=first_value, second=second_value):
                self.first.data = deepcopy(self.metadata)
                self.second.data = deepcopy(self.metadata)
                self.first.data["global_temperature"] = first_value
                self.second.data["global_temperature"] = second_value
                self.first.save(update_fields=["data"])
                self.second.save(update_fields=["data"])
                result = self.context(f"compare={self.first.pk},{self.second.pk}")
                temperature = next(row for row in result["rows"] if row["key"] == "temperature")
                self.assertEqual(temperature["status"], "different")
                self.assertEqual(temperature["cells"][0]["entries"][0]["value"], str(first_value) + " K")

    def test_original_parent_alias_conflicts_do_not_fall_back_to_rounded_grain_counts(self):
        """
        Propagate conflicting original phase and orientation parents despite float normalization
        """
        first = {"grain_count": "9007199254740992.0"}
        second = {"grain_count": "9007199254740993.0"}
        cases = (
            {"phase": [{"orientation": first, "Orientation": second}]},
            {"phase": [{"orientation": first}], "Phase": [{"orientation": second}]},
        )
        for data in cases:
            with self.subTest(data=data):
                original = deepcopy(data)
                cell = build_collection_summary(data)["comparison"]["fields"]["grain_count"]
                self.assertEqual(cell["state"], "ambiguous")
                self.assertEqual(cell["key"], "")
                self.assertEqual(cell["entries"][0]["state"], "ambiguous")
                self.assertNotIn("9007199254740992", cell["entries"][0]["value"])
                self.assertEqual(data, original)

    def test_output_availability_retains_component_count_associations_and_extra_series(self):
        """
        Distinguish swapped sample counts and additional unpaired mechanical components
        """
        first = deepcopy(self.metadata)
        first["stress"].update(stress_11=[1, 2], stress_22=[1, 2, 3])
        second = deepcopy(first)
        second["stress"].update(stress_11=[1, 2, 3], stress_22=[1, 2])
        self.assertNotEqual(build_collection_summary(first)["comparison"]["fields"]["outputs"]["key"],
                            build_collection_summary(second)["comparison"]["fields"]["outputs"]["key"])
        second = deepcopy(first)
        second["stress"]["stress_33"] = [1, 2]
        self.assertNotEqual(build_collection_summary(first)["comparison"]["fields"]["outputs"]["key"],
                            build_collection_summary(second)["comparison"]["fields"]["outputs"]["key"])

    def test_multiple_software_version_descriptions_remain_recorded(self):
        """
        Retain multiple accepted version descriptions without treating them as a conflict
        """
        data = deepcopy(self.metadata)
        data["simulation_software_version"] = "4.0"
        cell = build_collection_summary(data)["comparison"]["fields"]["software_version"]
        self.assertEqual(cell["state"], "recorded")
        self.assertEqual(cell["entries"][0]["value"], "3.0; 4.0")

    def test_output_alias_conflicts_never_claim_recorded_availability(self):
        """
        Keep conflicts inside mechanical groups incomplete even when one alias is empty
        """
        for group, component, alias in (("stress", "stress_11", "Stress 11"),
                                         ("total_strain", "strain_11", "Strain 11"),
                                         ("plastic_strain", "plastic_strain_11", "Plastic Strain 11")):
            for first in ([0, 1], []):
                with self.subTest(group=group, first=first):
                    data = deepcopy(self.metadata)
                    data[group] = {component: first, alias: [0, 2, 3]}
                    cell = build_collection_summary(data)["comparison"]["fields"]["outputs"]
                    self.assertEqual(cell["state"], "ambiguous")
                    self.assertEqual(cell["key"], "")
                    self.assertEqual(cell["entries"], [])
        data = deepcopy(self.metadata)
        data["Global Temperature"] = 310
        cell = build_collection_summary(data)["comparison"]["fields"]["outputs"]
        self.assertEqual(cell["state"], "recorded")
        self.assertTrue(cell["key"])

    def test_missing_ambiguous_and_truncated_values_never_claim_equality(self):
        """
        Keep absent units, conflicting aliases and shortened labels explicitly incomplete
        """
        data = deepcopy(self.metadata)
        data["Global Temperature"] = 310
        data["software"] = "x" * 1000
        data["units"].pop("Length")
        self.first.data = data
        self.first.save(update_fields=["data"])
        result = self.context(f"compare={self.first.pk},{self.second.pk}")
        rows = {row["key"]: row for row in result["rows"]}
        for key, state in (("temperature", "ambiguous"), ("software", "truncated"), ("rve_size", "not_supplied")):
            self.assertEqual(rows[key]["status"], "incomplete")
            self.assertEqual(rows[key]["cells"][0]["state"], state)
            self.assertIsNone(rows[key]["cells"][1]["matches_reference"])
        self.assertEqual(rows["temperature"]["cells"][0]["entries"][0]["value"], "Conflicting field names")

    def test_phase_entries_keep_order_and_model_parents_with_explicit_grain_alias(self):
        """
        Preserve identically named phases as separate entries without mixing their models
        """
        data = deepcopy(self.metadata)
        phase = deepcopy(data["phase"][0])
        phase["constitutive_model"]["plastic_model_name"] = "Other model"
        phase["orientation"].pop("grain_count")
        phase["orientation"]["grain_number"] = ["500"]
        data["phase"].append(phase)
        fields = build_collection_summary(data)["comparison"]["fields"]
        self.assertEqual([entry["context"] for entry in fields["plastic_model"]["entries"]], ["Phase 1", "Phase 2"])
        self.assertEqual(fields["plastic_model"]["entries"][1]["path"], "phase[1].constitutive_model.plastic_model_name")
        self.assertEqual(fields["grain_count"]["entries"][1]["value"], "500")
        data["phase"][1]["orientation"]["grain_count"] = 700
        fields = build_collection_summary(data)["comparison"]["fields"]
        self.assertEqual(fields["grain_count"]["state"], "ambiguous")

    def test_nested_conflicts_mark_only_the_correct_zero_based_phase_entry(self):
        """
        Translate one-based validation paths without moving conflicts to another phase
        """
        for index in (0, 1):
            for row, field, alias, first, second in (
                ("elastic_model", "elastic_model_name", "Elastic Model Name", "A", "B"),
                ("lattice_structure", "lattice_structure", "Lattice Structure", "FCC", "BCC"),
            ):
                with self.subTest(index=index, row=row):
                    data = deepcopy(self.metadata)
                    data["phase"].append(deepcopy(data["phase"][0]))
                    parent = data["phase"][index]
                    if row == "elastic_model":
                        parent = parent["constitutive_model"]
                    parent.update({field: first, alias: second})
                    cell = build_collection_summary(data)["comparison"]["fields"][row]
                    self.assertEqual(cell["state"], "ambiguous")
                    self.assertEqual(cell["key"], "")
                    self.assertEqual(cell["entries"][index]["state"], "ambiguous")
                    self.assertEqual(cell["entries"][1 - index]["state"], "recorded")
                    self.assertTrue(cell["entries"][index]["path"].startswith(f"phase[{index}]."))

    def test_nested_loading_conflicts_keep_the_correct_condition_and_sibling_fields(self):
        """
        Mark the conflicted condition field without discarding other recorded entries
        """
        for index in (0, 1):
            with self.subTest(index=index):
                data = deepcopy(self.metadata)
                data["mechanical_BC"].append(deepcopy(data["mechanical_BC"][0]))
                data["mechanical_BC"][index]["Loading Type"] = "strain"
                cell = build_collection_summary(data)["comparison"]["fields"]["loading"]
                self.assertEqual(cell["state"], "ambiguous")
                self.assertEqual(cell["key"], "")
                for position, entry in enumerate(cell["entries"]):
                    self.assertEqual(entry["state"], "ambiguous" if position == index * 2 else "recorded")

    def test_bounded_projection_marks_omissions_and_rejects_nonfinite_values(self):
        """
        Bound large Unicode labels and parent lists without losing completeness warnings
        """
        data = deepcopy(self.metadata)
        data["phase"] *= 100
        data["phase"][0]["phase_name"] = "材料" * 1000
        data["global_temperature"] = float("inf")
        projection = build_collection_summary(data)["comparison"]
        self.assertLessEqual(len(json.dumps(projection, ensure_ascii=False).encode()), MAX_PROJECTION_BYTES)
        self.assertEqual(projection["fields"]["phase"]["state"], "truncated")
        self.assertLessEqual(len(projection["fields"]["phase"]["entries"]), 8)
        self.assertEqual(projection["fields"]["temperature"]["state"], "ambiguous")
        self.assertNotIn("Infinity", json.dumps(projection))

    def test_canonical_selection_parser_rejects_duplicates_repeats_and_oversized_ids(self):
        """
        Reject malformed pin state rather than dropping or substituting selected records
        """
        invalid = ["compare=01,2", "compare=1,1", "compare=1&compare=2", "compare=1,2,3,4,5",
                   "compare=1,", "compare=0,2", "compare=-1,2", "compare=1,%202", "compare=1,9223372036854775808",
                   "compare=1.0,2", "compare=１,2"]
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(ValueError):
                parse_comparison_ids(QueryDict(query))
        self.assertEqual(parse_comparison_ids(QueryDict("compare=4,2,3,1")), [4, 2, 3, 1])
        self.assertEqual(parse_comparison_ids(QueryDict("compare=")), [])

    def test_all_selected_objects_must_be_accessible_collection_members(self):
        """
        Hide the entire matrix on missing access, nonmembers or invalid display arguments
        """
        outsider = JSONData.objects.create(owner=self.owner, data={"title": "Outside collection"})
        for extra in (self.hidden.pk, outsider.pk, 9223372036854775807):
            with self.subTest(extra=extra):
                result = self.context(f"compare={self.first.pk},{extra}")
                self.assertTrue(result["error"])
                self.assertEqual(result["objects"], [])
                self.assertEqual(result["rows"], [])
                self.assertNotIn("SECRET", json.dumps(result))
        for suffix in ("differences=2", "differences=1&differences=0"):
            self.assertTrue(self.context(f"compare={self.first.pk},{self.second.pk}&{suffix}")["error"])

    def test_warm_comparison_reads_no_original_data(self):
        """
        Use existing scalar projections for repeated comparison requests
        """
        with CaptureQueriesContext(connection) as queries:
            result = self.context(f"compare={self.first.pk},{self.second.pk}")
        self.assertTrue(result["ready"])
        self.assertTrue(queries)
        self.assertFalse(any('"pages_jsondata"."data"' in query["sql"] for query in queries))

    def test_one_pin_keeps_legacy_summary_and_two_pins_upgrade_only_selected(self):
        """
        Preserve discovery performance and migrate only the records needed by comparison
        """
        legacy = {"title": "Legacy", "identifier": "old", "groups": {}}
        JSONData.objects.all().update(collection_summary=legacy)
        result = self.context(f"compare={self.first.pk}")
        self.assertFalse(result["ready"])
        self.first.refresh_from_db()
        self.assertEqual(self.first.collection_summary, legacy)
        result = self.context(f"compare={self.first.pk},{self.second.pk}")
        self.assertTrue(result["ready"])
        self.hidden.refresh_from_db()
        self.assertEqual(self.hidden.collection_summary, legacy)
        self.first.refresh_from_db()
        self.assertEqual(self.first.collection_summary["summary_version"], SUMMARY_VERSION)

    def test_outdated_query_and_backfill_include_missing_json_keys_and_null_versions(self):
        """
        Upgrade legacy and null JSON versions on either supported database backend
        """
        originals = dict(JSONData.objects.values_list("pk", "data"))
        JSONData.objects.filter(pk=self.first.pk).update(collection_summary={"title": "Legacy"})
        JSONData.objects.filter(pk=self.second.pk).update(collection_summary={"summary_version": None})
        JSONData.objects.filter(pk=self.hidden.pk).update(collection_summary=None)
        self.assertEqual(JSONData.objects.filter(outdated_summary_query()).count(), 3)
        output = StringIO()
        call_command("backfill_collection_summaries", all=True, stdout=output)
        self.assertIn("Prepared 3 summaries. 0 records still need summaries.", output.getvalue())
        self.assertEqual(JSONData.objects.filter(outdated_summary_query()).count(), 0)
        self.assertEqual(dict(JSONData.objects.values_list("pk", "data")), originals)

    def test_incomplete_preparation_has_real_selected_counts_without_partial_rows(self):
        """
        Keep comparison preparation separate while retaining unknown-size operator feedback
        """
        JSONData.objects.filter(pk=self.first.pk).update(collection_summary={"title": "Legacy"}, size_bytes=0)
        result = self.context(f"compare={self.first.pk},{self.second.pk}")
        self.assertEqual(result["preparation"], {"ready_count": 1, "total_count": 2, "requires_admin": True})
        self.assertEqual([obj["pk"] for obj in result["objects"]], [self.first.pk, self.second.pk])
        self.assertEqual(result["objects"][0]["title"], "Legacy")
        self.assertEqual(result["rows"], [])
        self.assertFalse(result["ready"])

    def test_csv_is_access_checked_formula_safe_and_keeps_original_json(self):
        """
        Download bounded values with source context while protecting spreadsheet text cells
        """
        data = deepcopy(self.metadata)
        data["title"] = "=HYPERLINK(unsafe)"
        data["software"] = "\t@unsafe"
        self.first.data = data
        self.first.save(update_fields=["data"])
        self.client.force_login(self.owner)
        url = reverse("collection_comparison_export", args=[self.collection.pk])
        response = self.client.get(url, {"compare": f"{self.first.pk},{self.second.pk}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        rows = list(csv.DictReader(StringIO(response.content.decode())))
        first_rows = [row for row in rows if row["object_id"] == str(self.first.pk)]
        self.assertTrue(all(row["title"].startswith("'=") for row in first_rows))
        software = next(row for row in first_rows if row["field"] == "Software")
        self.assertEqual(software["value"], "'\t@unsafe")
        self.assertTrue(any(row["context"] == "Phase 1" and "phase[0]" in row["path"] for row in rows))
        differences = self.client.get(url, {"compare": f"{self.first.pk},{self.second.pk}", "differences": "1"})
        difference_rows = list(csv.DictReader(StringIO(differences.content.decode())))
        self.assertTrue(difference_rows)
        self.assertTrue(all(row["comparison_status"] != "same" for row in difference_rows))
        self.first.refresh_from_db()
        self.assertEqual(self.first.data, data)
        self.assertEqual(self.client.get(url, {"compare": f"{self.first.pk},{self.hidden.pk}"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"compare": str(self.first.pk)}).status_code, 400)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_csv_refuses_unprepared_rows_and_revoked_temporary_members(self):
        """
        Recheck an entire temporary selection even when its pinned subset remains accessible
        """
        self.client.force_login(self.owner)
        url = reverse("collection_comparison_export", args=[self.collection.pk])
        JSONData.objects.filter(pk=self.first.pk).update(collection_summary={"title": "Old"}, size_bytes=0)
        response = self.client.get(url, {"compare": f"{self.first.pk},{self.second.pk}"})
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Prepared 1 of 2", status_code=503)
        self.assertNotIn("Content-Disposition", response)
        selection = reverse("selection_comparison_export", args=["temporary-token"])
        with patch("apps.pages.study_comparison_views._selection_ids", return_value=[self.first.pk, self.second.pk, self.hidden.pk]):
            response = self.client.get(selection, {"compare": f"{self.first.pk},{self.second.pk}"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("SECRET", response.content.decode())
