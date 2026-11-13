"""
Keep candidate criteria and curve choices consistent throughout study navigation
"""

import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import CollectionRelationship, JSONData, ResearchCollection
from .study_comparison import SUMMARY_VERSION


class StudyDiscoveryIntegrationTests(TestCase):
    """
    Exercise real workspace views and signed return context with bounded preparation
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create a reference, different temperatures and an inaccessible collection member
        """
        cls.owner = User.objects.create_user(username="discovery-integration")
        cls.other = User.objects.create_user(username="discovery-other")
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Temperature study")
        cls.records = []
        for index in range(8):
            data = {"title": f"Recorded simulation {index}", "identifier": f"discovery-{index}",
                    "software": "DAMASK", "phase": [{"phase_name": "Copper"}],
                    "global_temperature": 300 + index * 10,
                    "units": {"Temperature": "K", "Stress": "MPa", "Strain": "1"},
                    "stress": {"equivalent_stress": [0, 1, 2]},
                    "total_strain": {"equivalent_strain": [0, .01, .02]}}
            cls.records.append(JSONData.objects.create(owner=cls.owner, data=data,
                                                       size_bytes=len(json.dumps(data).encode())))
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "SECRET hidden simulation"})
        cls.collection.members.add(*cls.records, cls.hidden)

    def setUp(self):
        """
        Authenticate the owner and retain the canonical collection route
        """
        self.client.force_login(self.owner)
        self.url = reverse("collection_detail", args=[self.collection.pk])

    def test_native_candidate_form_preserves_reference_and_filters(self):
        """
        Canonicalize actual checkbox controls and open an explained candidate comparison
        """
        response = self.client.get(self.url, {"compare": str(self.records[0].pk), "find_candidates": "1",
                                              "match_field": ["", "phase", "software"], "vary_field": "temperature"})
        self.assertEqual(response.status_code, 200)
        candidates = response.context["study_candidates"]
        self.assertTrue(candidates["ready"])
        self.assertEqual(candidates["counts"]["matching"], 7)
        self.assertNotContains(response, "SECRET hidden simulation")
        row = candidates["rows"][0]
        compared = self.client.get(row["compare_url"])
        self.assertEqual(compared.context["study_comparison"]["ids"], [self.records[0].pk, row["pk"]])
        self.assertEqual(compared.context["study_return_params"]["match_fields"], "software,phase")
        self.assertContains(compared, 'id="study-curves"')
        self.assertNotContains(compared, 'id="study-curves" open')

    def test_invalid_criteria_can_be_corrected_without_losing_the_reference(self):
        """
        Show a native field error without silently using defaults or dropping pinned records
        """
        response = self.client.get(self.url, {"compare": str(self.records[0].pk), "find_candidates": "1",
                                              "match_field": [""], "vary_field": "temperature"})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context["study_candidates"]["error"])
        self.assertEqual(response.context["study_candidates"]["rows"], [])
        self.assertEqual(response.context["study_comparison"]["ids"], [self.records[0].pk])
        fields = {field["name"]: field["value"] for field in response.context["study_candidates"]["form_hidden_fields"]}
        self.assertEqual(fields["compare"], str(self.records[0].pk))
        fields.update(match_field=["", "software"], vary_field="temperature")
        corrected = self.client.get(self.url, fields)
        self.assertEqual(corrected.status_code, 200)
        self.assertTrue(corrected.context["study_candidates"]["ready"])

    def test_clamped_candidate_page_is_canonical_in_signed_source_return(self):
        """
        Return to the displayed candidate page after an out-of-range page request
        """
        response = self.client.get(self.url, {"compare": str(self.records[0].pk), "find_candidates": "1",
                                              "candidates_page": "999"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["study_candidates"]["page"].number, 1)
        self.assertNotIn("candidates_page", response.context["study_return_params"])
        detail = self.client.get(response.context["study_candidates"]["rows"][0]["detail_url"])
        self.assertNotIn("candidates_page", parse_qs(urlsplit(detail.context["graph_return_url"]).query))

    def test_source_return_and_manual_save_retain_candidate_and_curve_choices(self):
        """
        Carry canonical criteria and explicit physical selectors through signed actions
        """
        params = {"compare": f"{self.records[0].pk},{self.records[1].pk}", "panel": "compare",
                  "find_candidates": "1", "match_fields": "software,phase", "vary_field": "temperature",
                  "curve_component": "11", "curve_strain": "plastic"}
        workspace = self.client.get(self.url, params)
        self.assertEqual(workspace.status_code, 200)
        self.assertTrue(workspace.context["study_curves"]["open"])
        detail = self.client.get(workspace.context["study_comparison"]["objects"][0]["detail_url"])
        returned = parse_qs(urlsplit(detail.context["graph_return_url"]).query)
        for key, value in params.items():
            self.assertEqual(returned[key], [value])
        saved = self.client.post(reverse("collection_relationship_save", args=[self.collection.pk]), {
            "source": self.records[0].pk, "target": self.records[1].pk, "label": "Compared settings",
            "graph_context": workspace.context["graph_context"],
        })
        self.assertEqual(saved.status_code, 302)
        returned = parse_qs(urlsplit(saved.url).query)
        for key in ("compare", "match_fields", "vary_field", "curve_component", "curve_strain"):
            self.assertEqual(returned[key], [params[key]])
        self.assertEqual(CollectionRelationship.objects.count(), 1)

    def test_discovery_and_comparison_share_one_preparation_budget(self):
        """
        Spend at most three preparation slots across graph, pins and all candidates
        """
        for obj in self.records:
            legacy = {key: value for key, value in obj.collection_summary.items()
                      if key not in {"summary_version", "comparison"}}
            JSONData.objects.filter(pk=obj.pk).update(collection_summary=legacy)
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_OBJECTS", 3):
            response = self.client.get(self.url, {"compare": f"{self.records[0].pk},{self.records[1].pk}",
                                                  "find_candidates": "1"})
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.context["study_comparison"]["ready"])
        self.assertFalse(response.context["study_candidates"]["ready"])
        self.assertEqual(response.context["study_candidates"]["rows"], [])
        self.assertEqual(response.context["study_candidates"]["preparation"]["ready_count"], 3)
        self.assertEqual(JSONData.objects.filter(owner=self.owner, collection_summary__summary_version=SUMMARY_VERSION).count(), 3)

    def test_curve_endpoint_uses_the_complete_current_selection(self):
        """
        Reach the bounded curve route through native workspace selectors
        """
        workspace = self.client.get(self.url, {"compare": f"{self.records[0].pk},{self.records[1].pk}", "panel": "compare"})
        response = self.client.get(workspace.context["study_curves"]["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["selection"], [self.records[0].pk, self.records[1].pk])
        self.assertTrue(response.json()["overlay_allowed"])
