"""
Find transparent comparison candidates without broadening scope or guessing missing metadata
"""

from copy import deepcopy
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.db import connection
from django.http import QueryDict
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .collection_graph import collection_summaries
from .models import JSONData, ResearchCollection
from .research_collections import accessible_objects
from .study_candidates import build_candidate_context, candidate_parameters


class StudyCandidateTests(TestCase):
    """
    Exercise evidence, complete selection validation and bounded preparation on real records
    """

    @classmethod
    def setUpTestData(cls):
        """
        Build a private collection with matching, incomplete and excluded records
        """
        cls.owner = User.objects.create_user(username="candidate-owner")
        cls.other = User.objects.create_user(username="candidate-other")
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Candidate study")
        cls.metadata = {
            "software": "DAMASK", "software_version": "3.0",
            "phase": [{"phase_name": "Copper", "orientation": {"grain_count": 343}}],
            "global_temperature": 300, "units": {"Temperature": "K"},
        }
        cls.reference = cls.record("Reference")
        cls.matching = cls.record("Temperature variant", global_temperature=350)
        cls.same = cls.record("Same temperature")
        cls.excluded = cls.record("Other software", software="Abaqus", global_temperature=350)
        cls.missing = cls.record("Missing temperature", global_temperature=None)
        cls.ambiguous = cls.record("Conflicting temperature", **{"Global Temperature": 310})
        cls.hidden = cls.record("SECRET hidden candidate", owner=cls.other, global_temperature=350)
        cls.outside = JSONData.objects.create(owner=cls.owner, data={**cls.metadata, "title": "Outside collection"})

    @classmethod
    def record(cls, title, owner=None, **changes):
        """
        Add one synthetic record using the normal summary preparation path

        Parameters
        ----------
        title : str
            Visible record title.
        owner : User or None, optional
            Alternative uploader for permission cases.
        **changes : object
            Top-level metadata changes.

        Returns
        -------
        JSONData
            Saved collection member.
        """
        data = {**deepcopy(cls.metadata), "title": title, **changes}
        record = JSONData.objects.create(owner=owner or cls.owner, data=data,
                                        size_bytes=len(json.dumps(data).encode()))
        cls.collection.members.add(record)
        return record

    def context(self, extra="", *, ids=None):
        """
        Build candidates from the same access-filtered collection query as the workspace

        Parameters
        ----------
        extra : str, optional
            Additional encoded criteria and page arguments.
        ids : list of int or None, optional
            Selection whose first record is the reference.

        Returns
        -------
        dict
            Candidate finder state and bounded evidence.
        """
        selected = ids if ids is not None else [self.reference.pk]
        params = QueryDict("find_candidates=1&compare=" + ",".join(map(str, selected)) + extra)
        return build_candidate_context(
            accessible_objects(self.owner).filter(research_collections=self.collection),
            {"ids": selected, "error": ""}, params,
            base_url=reverse("collection_detail", args=[self.collection.pk]),
            navigation_params={"panel": "compare", "differences": "1", "member_q": "copper"},
        )

    def test_initial_defaults_and_native_controls_have_one_canonical_representation(self):
        """
        Keep first-entry defaults distinct from a native submission with no selected fields
        """
        self.assertEqual(candidate_parameters(QueryDict("")), {})
        self.assertEqual(candidate_parameters(QueryDict("find_candidates=1")), {
            "find_candidates": "1", "match_fields": "software,phase", "vary_field": "temperature",
        })
        native = QueryDict("find_candidates=1&match_field=&match_field=phase&match_field=software&vary_field=temperature")
        self.assertEqual(candidate_parameters(native)["match_fields"], "software,phase")
        invalid = (
            "find_candidates=1&match_field=software&vary_field=temperature",
            "find_candidates=1&match_field=&vary_field=temperature",
            "find_candidates=1&match_field=software&match_field=&vary_field=temperature",
            "find_candidates=1&match_field=&match_field=&match_field=software&vary_field=temperature",
            "find_candidates=1&match_field=&match_field=software&match_field=software&vary_field=temperature",
            "find_candidates=1&match_fields=software&match_field=phase&vary_field=temperature",
            "find_candidates=1&match_fields=software,software&vary_field=temperature",
            "find_candidates=1&match_fields=outputs&vary_field=temperature",
            "find_candidates=1&match_fields=software&vary_field=software",
            "find_candidates=1&match_fields=software&vary_field=temperature&vary_field=phase",
            "find_candidates=1&match_fields=software&match_fields=phase&vary_field=temperature",
            "find_candidates=1&find_candidates=1",
            "find_candidates=0", "match_fields=software", "find_candidates=1&candidates_page=0",
            "find_candidates=1&candidates_page=01", "find_candidates=1&candidates_page=2147483648",
        )
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(ValueError):
                candidate_parameters(QueryDict(query))

    def test_invalid_native_criteria_retain_validated_reference_for_correction(self):
        """
        Keep the pinned reference when an empty checkbox submission needs correction
        """
        params = QueryDict(f"compare={self.reference.pk}&find_candidates=1&match_field=&vary_field=temperature")
        result = build_candidate_context(
            accessible_objects(self.owner).filter(research_collections=self.collection),
            {"ids": [self.reference.pk], "error": ""}, params,
            base_url=reverse("collection_detail", args=[self.collection.pk]),
            navigation_params={"compare": str(self.reference.pk), "panel": "compare"},
        )
        self.assertTrue(result["error"])
        hidden = {row["name"]: row["value"] for row in result["form_hidden_fields"]}
        self.assertEqual(hidden["compare"], str(self.reference.pk))
        self.assertEqual(hidden["find_candidates"], "1")
        self.assertIn(f"compare={self.reference.pk}", result["clear_url"])
        self.assertNotIn("match_field", result["clear_url"])

    def test_candidates_partition_the_accessible_collection_and_show_field_evidence(self):
        """
        Separate exact selected-field candidates from uncertain and excluded records
        """
        result = self.context()
        self.assertTrue(result["ready"])
        self.assertEqual(result["counts"], {"matching": 1, "uncertain": 2, "excluded": 2, "total": 5})
        self.assertEqual([row["pk"] for row in result["rows"]], [self.matching.pk])
        evidence = {item["key"]: item for item in result["rows"][0]["evidence"]}
        self.assertEqual(evidence["software"]["status"], "same")
        self.assertEqual(evidence["phase"]["status"], "same")
        self.assertEqual(evidence["temperature"]["status"], "different")
        self.assertEqual(evidence["temperature"]["reference"]["entries"][0]["value"], "300 K")
        self.assertEqual(evidence["temperature"]["candidate"]["entries"][0]["value"], "350 K")
        self.assertNotIn("SECRET", str(result))
        self.assertNotIn("Outside collection", str(result))
        self.assertNotIn("comparison", result["rows"][0])

    def test_known_mismatch_excludes_even_when_another_selected_field_is_incomplete(self):
        """
        Keep definitely unsuitable records outside the uncertain candidate list
        """
        mismatch = self.record("Wrong software and missing temperature", software="Other", global_temperature=None)
        result = self.context()
        self.assertEqual(result["counts"]["excluded"], 3)
        self.assertNotIn(mismatch.pk, [row["pk"] for row in result["uncertain_rows"]])

    def test_reference_requires_complete_chosen_fields_and_preserves_the_reason(self):
        """
        Ask for different criteria or a different reference rather than skipping missing fields
        """
        result = self.context(ids=[self.missing.pk])
        self.assertFalse(result["ready"])
        self.assertIn("reference", result["error"].lower())
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["reference"]["pk"], self.missing.pk)
        self.assertEqual(result["reference_missing_fields"], ["Global temperature"])

    def test_whole_selection_must_remain_accessible_members_before_any_preparation(self):
        """
        Reject hidden, nonmember and malformed comparison selections without cache work
        """
        for ids in ([self.reference.pk, self.hidden.pk], [self.reference.pk, self.outside.pk], [],
                    [self.reference.pk, self.reference.pk]):
            with self.subTest(ids=ids), patch("apps.pages.study_candidates.collection_summaries") as prepare:
                result = self.context(ids=ids)
                self.assertTrue(result["error"])
                self.assertFalse(result["ready"])
                self.assertEqual(result["rows"], [])
                prepare.assert_not_called()
                self.assertNotIn("SECRET", str(result))

    def test_warm_candidate_queries_do_not_read_original_json(self):
        """
        Find candidates from bounded scalar projections without loading curve arrays
        """
        with CaptureQueriesContext(connection) as queries:
            result = self.context()
        self.assertTrue(result["ready"])
        for query in queries:
            self.assertNotIn('"pages_jsondata"."data"', query["sql"])

    def test_comparison_links_keep_workspace_state_and_use_an_explicit_reference_pair(self):
        """
        Open one candidate beside the reference without mutating membership or losing criteria
        """
        result = self.context(ids=[self.reference.pk, self.same.pk])
        row = result["rows"][0]
        query = parse_qs(urlsplit(row["compare_url"]).query)
        self.assertEqual(query["compare"], [f"{self.reference.pk},{self.matching.pk}"])
        self.assertEqual(query["panel"], ["compare"])
        self.assertEqual(query["differences"], ["1"])
        self.assertEqual(query["match_fields"], ["software,phase"])
        self.assertEqual(query["member_q"], ["copper"])
        pinned = parse_qs(urlsplit(row["pin_url"]).query)
        self.assertEqual(pinned["compare"], [f"{self.reference.pk},{self.same.pk},{self.matching.pk}"])
        self.assertEqual(self.collection.members.count(), 7)

    def test_pagination_and_uncertain_preview_have_explicit_bounds_and_exact_counts(self):
        """
        Page complete candidates and keep an explicitly limited incomplete preview
        """
        for index in range(28):
            self.record(f"Variant {index}", global_temperature=400 + index)
        for index in range(12):
            self.record(f"Uncertain {index}", global_temperature=None)
        result = self.context()
        self.assertEqual(result["counts"]["matching"], 29)
        self.assertEqual(result["counts"]["uncertain"], 14)
        self.assertEqual(len(result["rows"]), 25)
        self.assertEqual(len(result["uncertain_rows"]), 10)
        self.assertEqual(result["uncertain_limit"], 10)
        self.assertIn("candidates_page=2", result["next_url"])
        second = self.context("&candidates_page=2")
        self.assertEqual(len(second["rows"]), 4)
        self.assertEqual(second["page"].number, 2)
        self.assertTrue(second["previous_url"])

    def test_old_cache_preparation_has_no_partial_candidate_results(self):
        """
        Preserve real preparation progress while withholding incomplete candidate searches
        """
        self.record("Additional variant", global_temperature=360)
        JSONData.objects.filter(research_collections=self.collection).update(collection_summary=None)
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_OBJECTS", 1):
            result = self.context()
        self.assertFalse(result["ready"])
        self.assertIsNotNone(result["preparation"])
        self.assertEqual(result["preparation"]["total_count"], 7)
        self.assertEqual(result["preparation"]["ready_count"], 1)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["uncertain_rows"], [])
        self.assertNotIn("SECRET", str(result))

    def test_unknown_size_outdated_cache_requires_operator_preparation(self):
        """
        Avoid pulling unknown original arrays into an interactive candidate search
        """
        JSONData.objects.filter(pk=self.matching.pk).update(collection_summary={}, size_bytes=0)
        result = self.context()
        self.assertTrue(result["preparation"]["requires_admin"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["rows"], [])

    def test_precision_types_parent_order_and_partial_values_are_not_guessed(self):
        """
        Reuse typed complete fingerprints and retain ambiguous or truncated criteria
        """
        self.reference.data["global_temperature"] = "300.00000000000000001"
        self.reference.save(update_fields=["data"])
        precise = self.record("Precise variant", global_temperature="300.00000000000000002")
        result = self.context()
        self.assertIn(precise.pk, [row["pk"] for row in result["rows"]])
        truncated = self.record("Long phase", phase=[{"phase_name": "x" * 1000}], global_temperature=350)
        result = self.context()
        self.assertIn(truncated.pk, [row["pk"] for row in result["uncertain_rows"]])
        evidence = next(row for row in result["uncertain_rows"] if row["pk"] == truncated.pk)["evidence"]
        self.assertEqual(next(item for item in evidence if item["key"] == "phase")["status"], "incomplete")

    def test_access_change_during_summary_read_does_not_reveal_cached_candidates(self):
        """
        Recheck the accessible collection before exposing cached candidate titles
        """
        self.matching.owner = self.other
        self.matching.access_type = "all"
        self.matching.save(update_fields=["owner", "access_type"])

        def read_then_revoke(objects, **kwargs):
            """
            Revoke one visible record after the bounded metadata read completes

            Parameters
            ----------
            objects : QuerySet
                Accessible members passed to summary preparation.
            **kwargs : object
                Normal summary preparation options.

            Returns
            -------
            list of dict
                Metadata fetched before the access change.
            """
            rows = list(collection_summaries(objects, **kwargs))
            JSONData.objects.filter(pk=self.matching.pk).update(access_type="c")
            return rows

        with patch("apps.pages.study_candidates.collection_summaries", side_effect=read_then_revoke):
            result = self.context()
        self.assertFalse(result["ready"])
        self.assertTrue(result["error"])
        self.assertEqual(result["rows"], [])
        self.assertNotIn("Temperature variant", str(result))
