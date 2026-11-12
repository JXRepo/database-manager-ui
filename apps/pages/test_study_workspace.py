"""
Keep comparison selections private and stable across collection navigation
"""

from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import CollectionRelationship, JSONData, ResearchCollection


class StudyWorkspaceTests(TestCase):
    """
    Exercise native selection, browsing and signed return links through real views
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create multiple member pages and a private inaccessible member
        """
        cls.owner = User.objects.create_user(username="study-workspace-owner")
        cls.other = User.objects.create_user(username="study-workspace-other")
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Copper study")
        cls.records = []
        for number in range(32):
            cls.records.append(JSONData.objects.create(owner=cls.owner, data={
                "identifier": f"study-{number}", "title": f"Copper run {number:02}",
                "software": "Recorded solver", "software_version": "1.0",
                "phase": [{"phase_name": "Copper"}],
                "mechanical_BC": [{"loading_type": "stress", "loading_mode": "cyclic"}],
            }))
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "SECRET inaccessible run"})
        cls.collection.members.add(*cls.records, cls.hidden)
        cls.relationship = CollectionRelationship.objects.create(
            collection=cls.collection, source=cls.records[0], target=cls.records[-1], label="Compared with",
        )

    def setUp(self):
        """
        Authenticate the private collection owner
        """
        self.client.force_login(self.owner)
        self.url = reverse("collection_detail", args=[self.collection.pk])

    def test_pins_preserve_order_and_focus_without_reducing_collection_members(self):
        """
        Pin records across pages while retaining full member counts and source links
        """
        ids = [self.records[0].pk, self.records[-1].pk, self.records[7].pk]
        response = self.client.get(self.url, {"compare": ",".join(map(str, ids)), "panel": "compare"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object_total"], 32)
        study = response.context["study_comparison"]
        self.assertEqual([row["pk"] for row in study["objects"]], ids)
        self.assertTrue(study["ready"])
        graph_ids = {node["object_pk"] for node in response.context["relationship_graph"]["nodes"]
                     if "object_pk" in node}
        self.assertEqual(graph_ids, set(ids))
        self.assertEqual(response.context["study_workspace"]["browser_page"].paginator.count, 32)
        self.assertEqual(len(response.context["study_workspace"]["browser_rows"]), 25)
        self.assertNotContains(response, "SECRET inaccessible run")

    def test_browser_search_and_page_links_retain_complete_selection(self):
        """
        Search complete words in accessible summaries without losing previous pins
        """
        selection = f"{self.records[0].pk},{self.records[-1].pk}"
        response = self.client.get(self.url, {"compare": selection, "member_q": "copper 08"})
        workspace = response.context["study_workspace"]
        self.assertEqual([row["pk"] for row in workspace["browser_rows"]], [self.records[8].pk])
        added = self.client.get(workspace["browser_rows"][0]["pin_url"])
        self.assertEqual(added.context["study_comparison"]["ids"],
                         [self.records[0].pk, self.records[-1].pk, self.records[8].pk])
        response = self.client.get(self.url, {"compare": selection, "member_q": "cop"})
        self.assertEqual(response.context["study_workspace"]["browser_rows"], [])
        response = self.client.get(self.url, {"compare": selection, "members_page": "2"})
        self.assertEqual(len(response.context["study_workspace"]["browser_rows"]), 7)
        self.assertEqual(parse_qs(urlsplit(response.context["study_workspace"]["previous_url"]).query)["compare"], [selection])

    def test_reference_remove_and_clear_are_explicit_native_links(self):
        """
        Reorder the reference and clear comparison without changing stored membership
        """
        ids = [row.pk for row in self.records[:4]]
        response = self.client.get(self.url, {"compare": ",".join(map(str, ids)), "panel": "compare"})
        objects = response.context["study_comparison"]["objects"]
        reordered = self.client.get(objects[2]["reference_url"])
        self.assertEqual(reordered.context["study_comparison"]["ids"], [ids[2], ids[0], ids[1], ids[3]])
        reduced = self.client.get(objects[1]["remove_url"])
        self.assertEqual(reduced.context["study_comparison"]["ids"], [ids[0], ids[2], ids[3]])
        cleared = self.client.get(response.context["study_workspace"]["clear_url"])
        self.assertEqual(cleared.context["study_comparison"]["ids"], [])
        self.assertEqual(self.collection.members.count(), 33)

    def test_invalid_selection_fails_closed_and_can_be_cleared(self):
        """
        Reject inaccessible, repeated and oversized pin selections without partial tables
        """
        invalid = [f"{self.records[0].pk},{self.hidden.pk}", "1,1", "1,2,3,4,5", "0,1", "01,2"]
        for value in invalid:
            with self.subTest(value=value):
                response = self.client.get(self.url, {"compare": value, "panel": "compare"})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.context["study_comparison"]["ready"])
                self.assertEqual(response.context["study_comparison"]["objects"], [])
                self.assertNotContains(response, "SECRET inaccessible run", status_code=400)
                self.assertEqual(self.client.get(response.context["study_workspace"]["clear_url"]).status_code, 200)

    def test_source_detail_return_retains_comparison_reference_and_browser_scope(self):
        """
        Return from source metadata to the same private comparison and browser page
        """
        selection = f"{self.records[-1].pk},{self.records[0].pk}"
        response = self.client.get(self.url, {"compare": selection, "panel": "compare", "members_page": "2", "differences": "1"})
        source = response.context["study_comparison"]["objects"][0]
        detail = self.client.get(source["detail_url"])
        query = parse_qs(urlsplit(detail.context["graph_return_url"]).query)
        self.assertEqual(query["compare"], [selection])
        self.assertEqual(query["panel"], ["compare"])
        self.assertEqual(query["members_page"], ["2"])
        self.assertEqual(query["differences"], ["1"])

    def test_relationship_focus_does_not_discard_the_current_comparison(self):
        """
        Inspect a saved edge and retain pins for returning to the comparison
        """
        ids = [self.records[2].pk, self.records[3].pk]
        response = self.client.get(self.url, {"compare": ",".join(map(str, ids)), "panel": "compare"})
        focused = self.client.get(response.context["manual_editor"]["rows"][0]["edit_url"])
        self.assertEqual(focused.context["study_comparison"]["ids"], ids)
        self.assertEqual(focused.context["manual_selected"]["id"], self.relationship.pk)
        self.assertEqual(focused.context["study_workspace"]["panel"], "explore")

    def test_native_relationship_save_errors_and_delete_retain_signed_study_state(self):
        """
        Keep pins and browser scope while native relationship actions focus their result
        """
        ids = [self.records[-1].pk, self.records[0].pk]
        selection = ",".join(map(str, ids))
        scope = {"compare": selection, "panel": "compare", "member_q": "copper", "members_page": "2", "differences": "1"}
        workspace = self.client.get(self.url, scope)
        workspace = self.client.get(workspace.context["study_workspace"]["explore_url"])
        token = workspace.context["graph_context"]
        self.assertContains(workspace, 'name="graph_context"')
        save_url = reverse("collection_relationship_save", args=[self.collection.pk])
        fields = {"source": ids[0], "target": ids[1], "label": "Explicit comparison", "graph_context": token}
        invalid = self.client.post(save_url, {**fields, "target": ids[0]})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.context["study_comparison"]["ids"], ids)
        self.assertEqual(invalid.context["study_workspace"]["panel"], "explore")
        self.assertEqual(invalid.context["manual_editor"]["form"]["label"].value(), "Explicit comparison")
        saved = self.client.post(save_url, fields)
        self.assertEqual(saved.status_code, 302)
        query = parse_qs(urlsplit(saved.url).query)
        for key in ("compare", "member_q", "members_page", "differences"):
            self.assertEqual(query[key], [scope[key]])
        self.assertEqual(query["panel"], ["explore"])
        self.assertEqual(query["links"], ["members"])
        self.assertNotIn("group", query)
        relationship = CollectionRelationship.objects.get(label="Explicit comparison")
        self.assertEqual(query["edge"], [str(relationship.pk)])
        saved_workspace = self.client.get(saved.url)
        delete_url = reverse("collection_relationship_delete", args=[self.collection.pk, relationship.pk])
        deleted = self.client.post(delete_url, {"revision": relationship.revision,
                                                "graph_context": saved_workspace.context["graph_context"]})
        self.assertEqual(deleted.status_code, 302)
        query = parse_qs(urlsplit(deleted.url).query)
        self.assertEqual(query["compare"], [selection])
        self.assertEqual(query["differences"], ["1"])
        self.assertNotIn("edge", query)
        self.assertEqual(self.client.get(deleted.url).context["study_comparison"]["ids"], ids)
        self.assertFalse(CollectionRelationship.objects.filter(pk=relationship.pk).exists())

    def test_deleted_relationship_error_keeps_signed_comparison_and_submitted_draft(self):
        """
        Recover from a stale edge without losing native form values behind a graph error
        """
        ids = [self.records[0].pk, self.records[-1].pk]
        workspace = self.client.get(self.url, {"compare": ",".join(map(str, ids)), "edge": self.relationship.pk})
        relationship_pk = self.relationship.pk
        CollectionRelationship.objects.filter(pk=relationship_pk).delete()
        response = self.client.post(reverse("collection_relationship_save", args=[self.collection.pk]), {
            "source": ids[0], "target": ids[1], "label": "Preserve my changed wording",
            "relationship_id": relationship_pk, "revision": 1, "graph_context": workspace.context["graph_context"],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.context.get("manual_editor"))
        self.assertEqual(response.context["manual_editor"]["form"]["label"].value(), "Preserve my changed wording")
        self.assertEqual(response.context["study_comparison"]["ids"], ids)

    def test_signed_relationship_mutations_reject_repeated_query_and_wrong_workspace_tokens(self):
        """
        Reject untrusted continuation state before creating or deleting any relationship
        """
        own = self.client.get(self.url, {"compare": f"{self.records[0].pk},{self.records[1].pk}"})
        token = own.context["graph_context"]
        other_collection = ResearchCollection.objects.create(owner=self.owner, title="Different study")
        other_collection.members.add(*self.records[:2])
        other = self.client.get(reverse("collection_detail", args=[other_collection.pk]),
                                {"compare": f"{self.records[0].pk},{self.records[1].pk}"})
        foreign_token = other.context["graph_context"]
        save_url = reverse("collection_relationship_save", args=[self.collection.pk])
        delete_url = reverse("collection_relationship_delete", args=[self.collection.pk, self.relationship.pk])
        for supplied, query in (([token, token], ""), (foreign_token, ""), (token, "?graph_context=invalid"),
                                (token, "?compare=1,2"), ("invalid", "")):
            with self.subTest(query=query, supplied=supplied):
                response = self.client.post(save_url + query, {"source": self.records[1].pk, "target": self.records[2].pk,
                                                               "label": "Must not save", "graph_context": supplied})
                self.assertEqual(response.status_code, 400)
                response = self.client.post(delete_url + query, {"revision": 1, "graph_context": supplied})
                self.assertEqual(response.status_code, 400)
        self.assertFalse(CollectionRelationship.objects.filter(label="Must not save").exists())
        self.assertTrue(CollectionRelationship.objects.filter(pk=self.relationship.pk).exists())

    def test_temporary_collection_save_keeps_compare_state_and_rejects_wrong_target(self):
        """
        Carry the temporary comparison into its saved collection through native forms
        """
        ids = [self.records[1].pk, self.records[0].pk]
        created = self.client.post(reverse("graph_selection_create"), {"selected_objects": [obj.pk for obj in self.records]})
        selection_url = created.url
        workspace = self.client.get(selection_url, {"compare": ",".join(map(str, ids)), "panel": "compare",
                                                    "member_q": "copper", "members_page": "2", "differences": "1"})
        token = workspace.context["selection_token"]
        context_token = workspace.context["graph_context"]
        save_url = reverse("collection_save", args=[token])
        invalid = self.client.post(save_url, {"title": "", "graph_context": context_token})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.context["study_comparison"]["ids"], ids)
        self.assertEqual(invalid.context["study_workspace"]["panel"], "compare")
        collection_context = self.client.get(self.url).context["graph_context"]
        wrong_target = self.client.post(save_url, {"title": "Do not create", "graph_context": collection_context})
        self.assertEqual(wrong_target.status_code, 400)
        self.assertFalse(ResearchCollection.objects.filter(title="Do not create").exists())
        saved = self.client.post(save_url, {"title": "Saved comparison", "graph_context": context_token})
        self.assertEqual(saved.status_code, 302)
        final = self.client.get(saved.url)
        self.assertEqual(final.context["study_comparison"]["ids"], ids)
        self.assertEqual(final.context["study_workspace"]["panel"], "compare")
        self.assertEqual(final.context["study_workspace"]["browser_page"].number, 2)
        self.assertTrue(final.context["study_comparison"]["differences"])
        self.assertEqual(final.context["collection"].title, "Saved comparison")
        self.assertEqual(final.context["object_total"], 32)
