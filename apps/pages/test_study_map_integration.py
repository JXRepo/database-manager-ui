"""
Exercise parameter maps and detailed settings through the complete study workflow
"""

import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData, ResearchCollection
from .study_comparison import SUMMARY_VERSION


class StudyMapIntegrationTests(TestCase):
    """
    Keep map selection, parameter inspection and signed navigation connected
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create four distinct recorded conditions and an unavailable collection member
        """
        cls.owner = User.objects.create_user(username="map-integration")
        cls.other = User.objects.create_user(username="map-integration-other")
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Recorded temperature study")
        cls.records = []
        for index, (temperature, count) in enumerate(((298, 10000), (323, 10000), (298, 50000), (323, 50000))):
            data = {"title": f"Simulation {index}", "identifier": f"map-integration-{index}",
                    "software": "DAMASK", "global_temperature": temperature, "discretization_count": count,
                    "units": {"Temperature": "K", "Stress": "MPa", "Strain": "1"},
                    "phase": [{"phase_name": "Copper", "constitutive_model": {
                        "elastic_model_name": "Recorded elasticity", "elastic_parameters": {"C11": 100 + index},
                        "units": {"C11": "GPa"}}}],
                    "mechanical_BC": [{"loading_type": "stress", "loading_mode": "cyclic", "magnitude": 10 + index}],
                    "stress": {"equivalent_stress": [0, 1, 2]},
                    "total_strain": {"equivalent_strain": [0, .01, .02]}}
            obj = JSONData.objects.create(owner=cls.owner, data=data, size_bytes=len(json.dumps(data).encode()))
            cls.records.append(obj)
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "SECRET inaccessible map record"})
        cls.collection.members.add(*cls.records, cls.hidden)

    def setUp(self):
        """
        Authenticate the owner and use the real collection workspace
        """
        self.client.force_login(self.owner)
        self.url = reverse("collection_detail", args=[self.collection.pk])

    def test_cell_selection_filters_members_and_keeps_pins_across_cells(self):
        """
        Pick records from separate cells and carry their order into comparison
        """
        overview = self.client.get(self.url, {"panel": "map"})
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.context["study_map"]["counts"]["total"], 4)
        self.assertNotContains(overview, "SECRET inaccessible map record")
        cells = [cell for row in overview.context["study_map"]["rows"] for cell in row["cells"] if cell["count"]]
        selected = self.client.get(cells[0]["url"])
        browser = selected.context["study_workspace"]
        self.assertEqual(browser["browser_page"].paginator.count, 1)
        first = browser["browser_rows"][0]["pk"]
        pinned = self.client.get(browser["browser_rows"][0]["pin_url"])
        self.assertEqual(pinned.context["study_comparison"]["ids"], [first])
        second_cell = next(cell for row in pinned.context["study_map"]["rows"] for cell in row["cells"]
                           if cell["count"] and not cell["selected"])
        selected = self.client.get(second_cell["url"])
        second = selected.context["study_workspace"]["browser_rows"][0]
        pinned = self.client.get(second["pin_url"])
        compared = self.client.get(pinned.context["study_workspace"]["compare_url"])
        self.assertEqual(compared.context["study_comparison"]["ids"], [first, second["pk"]])
        self.assertTrue(compared.context["study_comparison"]["ready"])
        self.assertContains(compared, 'id="study-parameters-open"')

    def test_detailed_inspection_is_explicit_and_reveals_parameter_values(self):
        """
        Keep ordinary metadata comparison cached and load precise settings on request
        """
        params = {"panel": "compare", "compare": f"{self.records[0].pk},{self.records[1].pk}"}
        with patch("apps.pages.study_details.build_parameter_context") as inspect:
            comparison = self.client.get(self.url, params)
        inspect.assert_not_called()
        inspected = self.client.get(comparison.context["study_comparison"]["inspect_url"])
        self.assertEqual(inspected.status_code, 200)
        details = inspected.context["study_details"]
        self.assertTrue(details["ready"])
        row = next(row for row in details["rows"] if row["path"].endswith("elastic_parameters.C11"))
        self.assertEqual(row["status"], "different")
        self.assertEqual([cell["value"] for cell in row["cells"]], ["100", "101"])
        self.assertGreater(details["counts"]["different"], 0)

    def test_inspection_sources_and_mutations_preserve_signed_map_state(self):
        """
        Return to the same map coordinates and inspection after opening source data
        """
        overview = self.client.get(self.url, {"panel": "map"})
        selected = self.client.get(overview.context["study_map"]["rows"][0]["url"])
        params = dict(selected.context["study_return_params"])
        params.update(panel="compare", inspect="1", compare=f"{self.records[0].pk},{self.records[1].pk}")
        inspected = self.client.get(self.url, params)
        self.assertEqual(inspected.status_code, 200)
        detail = self.client.get(inspected.context["study_details"]["objects"][0]["detail_url"])
        returned = parse_qs(urlsplit(detail.context["graph_return_url"]).query)
        for key in ("map_row", "map_unit", "inspect", "compare"):
            self.assertEqual(returned[key], [params[key]])
        saved = self.client.post(reverse("collection_relationship_save", args=[self.collection.pk]), {
            "source": self.records[0].pk, "target": self.records[1].pk, "label": "Parameter comparison",
            "graph_context": inspected.context["graph_context"],
        })
        self.assertEqual(saved.status_code, 302)
        returned = parse_qs(urlsplit(saved.url).query)
        for key in ("map_row", "map_unit", "inspect", "compare"):
            self.assertEqual(returned[key], [params[key]])

    def test_map_and_comparison_share_the_same_preparation_allowance(self):
        """
        Withhold complete map counts until all accessible projections are prepared
        """
        for obj in self.records:
            legacy = {key: value for key, value in obj.collection_summary.items() if key != "parameter_map"}
            legacy["summary_version"] = 2
            JSONData.objects.filter(pk=obj.pk).update(collection_summary=legacy)
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_OBJECTS", 3):
            response = self.client.get(self.url, {"panel": "map", "compare": f"{self.records[0].pk},{self.records[1].pk}"})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.context["study_map"]["ready"])
        self.assertEqual(response.context["study_map"]["rows"], [])
        self.assertEqual(response.context["study_workspace"]["browser_rows"], [])
        self.assertFalse(response.context["study_workspace"]["map_selection"])
        self.assertNotContains(response, 'id="study-member-browser"', status_code=202)
        self.assertEqual(JSONData.objects.filter(owner=self.owner, collection_summary__summary_version=SUMMARY_VERSION).count(), 3)

    def test_invalid_controls_never_expand_a_map_selection(self):
        """
        Reject malformed and stale map selections without returning member rows
        """
        for extra in ({"map_cell": "bad"}, {"map_cell": "0" * 64}, {"map_x": "temperature", "map_y": "temperature"},
                      {"inspect": "yes"}, {"map_x_page": ["1", "2"]}):
            with self.subTest(extra=extra):
                response = self.client.get(self.url, {"panel": "map", **extra})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.context["study_workspace"]["browser_rows"], [])
                self.assertFalse(response.context["study_map"]["ready"])
                self.assertNotContains(response, "SECRET inaccessible map record", status_code=400)

    def test_collection_entry_opens_map_and_sources_restore_canonical_pages(self):
        """
        Start discovery directly and discard stale page numbers before signing links
        """
        index = self.client.get(reverse("collection_index"))
        self.assertContains(index, self.url + "?panel=map")
        response = self.client.get(self.url, {"panel": "map", "map_x_page": "999", "map_y_page": "999"})
        self.assertEqual(response.status_code, 200)
        for key in ("map_x_page", "map_y_page"):
            self.assertNotIn(key, response.context["study_return_params"])
        source = self.client.get(response.context["study_workspace"]["browser_rows"][0]["show_url"])
        self.assertEqual(parse_qs(urlsplit(source.context["graph_return_url"]).query)["panel"], ["map"])
