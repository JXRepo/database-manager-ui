"""
Verify manual annotations remain distinct, accessible and navigable in collection graphs
"""

from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from .collection_graph import MAX_VISIBLE_MANUAL_EDGES, build_collection_context
from .models import CollectionRelationship, JSONData, ResearchCollection


class ManualRelationshipGraphTests(TestCase):
    """
    Exercise graph overlays and focused links using real persisted collections
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create more than one member page and one cross-page annotation
        """
        cls.user = User.objects.create_user(username="manual-graph-owner")
        cls.collection = ResearchCollection.objects.create(owner=cls.user, title="Comparison study")
        cls.records = [JSONData.objects.create(owner=cls.user, data={
            "title": f"Simulation {index:02}", "identifier": f"manual-graph-{index}",
            "software": "Solver", "relation": "10.1234/reported",
        }) for index in range(30)]
        cls.collection.members.add(*cls.records)
        cls.edge = CollectionRelationship.objects.create(
            collection=cls.collection, source=cls.records[0], target=cls.records[-1], label="compared with",
        )

    def context(self, query, edges=None):
        """
        Build a graph with a fixed accessible membership and explicit links

        Parameters
        ----------
        query : str
            Encoded workspace arguments.
        edges : list of dict or None, optional
            Explicit annotations, defaulting to the saved cross-page connection.

        Returns
        -------
        dict
            Graph and navigation context.
        """
        if edges is None:
            edges = list(self.collection.relationships.values("id", "source_id", "target_id", "label", "revision"))
        return build_collection_context(self.collection.members.all(), title=self.collection.title,
                                        base_url=reverse("collection_detail", args=[self.collection.pk]),
                                        params=QueryDict(query), manual_relationships=edges)

    def test_cross_page_focus_shows_both_endpoints_and_preserves_navigation(self):
        """
        Focus a saved link independently from member pagination and return to it
        """
        context = self.context(f"edge={self.edge.pk}&view=detailed&page=2")
        graph = context["relationship_graph"]
        self.assertEqual(context["links_mode"], "members")
        self.assertEqual({row["pk"] for row in context["object_rows"]}, {self.edge.source_id, self.edge.target_id})
        self.assertEqual(context["object_total"], 30)
        edge = next(row for row in graph["edges"] if row["manual_id"])
        self.assertEqual(edge["source"], f"collection-object-{self.edge.source_id}")
        self.assertEqual(edge["target"], f"collection-object-{self.edge.target_id}")
        self.assertTrue(edge["label"].startswith("Manual: "))
        self.assertIn(f"edge={self.edge.pk}", context["graph_compact_url"])
        self.assertNotIn("edge=", context["overview_url"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("collection_detail", args=[self.collection.pk]), {"edge": self.edge.pk})
        detail = self.client.get(response.context["object_rows"][0]["detail_url"])
        return_params = parse_qs(urlsplit(detail.context["graph_return_url"]).query)
        self.assertEqual(return_params["edge"], [str(self.edge.pk)])

    def test_other_pages_keep_annotations_outside_the_page_in_the_list(self):
        """
        Keep counts exact without adding off-page graph nodes or invented endpoints
        """
        context = self.context("links=members")
        self.assertEqual(len(context["object_rows"]), 25)
        self.assertEqual(context["manual_visible"], [])
        self.assertEqual(len(context["manual_relationship_rows"]), 1)
        self.assertFalse(any(row["manual_id"] for row in context["relationship_graph"]["edges"]))

    def test_manual_graph_caps_rendered_edges_but_retains_all_annotations(self):
        """
        Bound dense graph output while retaining complete editor records and focus
        """
        edges = [{"id": index + 1, "source_id": self.records[-1].pk, "target_id": self.records[-2].pk,
                  "label": f"Observation {index}", "revision": 1} for index in range(130)]
        context = self.context("links=members", edges=edges)
        self.assertEqual(context["manual_visible_total"], 130)
        self.assertEqual(len(context["manual_visible"]), MAX_VISIBLE_MANUAL_EDGES)
        manual_paths = [edge["path"] for edge in context["relationship_graph"]["edges"] if edge["manual_id"]]
        self.assertEqual(len(set(manual_paths)), MAX_VISIBLE_MANUAL_EDGES)
        focused = self.context("edge=130", edges=edges)
        self.assertEqual([edge["id"] for edge in focused["manual_visible"]], [130])
        graph = focused["relationship_graph"]
        self.assertGreater(graph["width"], max(node["x"] + 232 for node in graph["nodes"]))
        self.assertEqual(len(graph["layouts"]["compact"]["paths"]), graph["count"])
        self.assertEqual(len(graph["layouts"]["detailed"]["paths"]), graph["count"])

    def test_invalid_or_unavailable_focus_does_not_broaden_the_graph(self):
        """
        Reject bad selectors and exclude both-endpoint inaccessible annotations
        """
        for query in ("edge=0", "edge=abc", "edge=1&edge=2", "edge=999999999999999999999"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.context(query)
        hidden = [{"id": 999, "source_id": self.edge.source_id, "target_id": 999999,
                   "label": "Hidden relationship", "revision": 1}]
        context = self.context("links=members", hidden)
        self.assertEqual(context["manual_relationship_rows"], [])
        with self.assertRaises(ValueError):
            self.context("edge=999", hidden)
