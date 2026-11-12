"""
Exercise continued selection and private return navigation through real views
"""

import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import signing
from django.test import Client, TestCase
from django.urls import reverse

from .collection_navigation import CONTEXT_MAX_AGE, CONTEXT_SALT
from .models import JSONData, ResearchCollection
from .research_collections import SELECTION_SESSION_KEY


class CollectionNavigationTests(TestCase):
    """
    Keep continuation bound to the original owner and complete accessible selection
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create distinguishable records and a private named research collection
        """
        cls.owner = User.objects.create_user(username="navigation-owner")
        cls.other = User.objects.create_user(username="navigation-other")
        cls.owned = JSONData.objects.create(owner=cls.owner, data={
            "title": "Copper tensile baseline", "identifier": "navigation-owned", "software": "DAMASK",
        })
        cls.second = JSONData.objects.create(owner=cls.owner, data={
            "title": "Steel tensile comparison", "identifier": "navigation-second", "software": "ABAQUS",
        })
        cls.public = JSONData.objects.create(owner=cls.other, access_type="all", data={
            "title": "Copper public comparison", "identifier": "navigation-public", "software": "DAMASK",
        })
        cls.shared = JSONData.objects.create(owner=cls.other, data={"title": "Shared copper"})
        cls.shared.shared_users.add(cls.owner)
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "Invisible material"})
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Private research title")
        cls.collection.members.add(cls.owned)

    def setUp(self):
        """
        Start every flow in the collection owner's authenticated browser
        """
        self.client.force_login(self.owner)

    def workspace(self, *, selection=False, objects=None, params=None):
        """
        Open a saved or temporary workspace through its normal endpoints

        Parameters
        ----------
        selection : bool, optional
            Create a new temporary selection instead of using the fixture collection.
        objects : list of JSONData or None, optional
            Records for the temporary selection.
        params : dict or None, optional
            Initial graph grouping and page.

        Returns
        -------
        HttpResponse
            Workspace with a signed navigation context.
        """
        url = reverse("collection_detail", args=[self.collection.pk])
        if selection:
            response = self.client.post(reverse("graph_selection_create"), {
                "selected_objects": [obj.pk for obj in (objects or [self.owned])],
            })
            self.assertEqual(response.status_code, 302)
            url = response.url
        response = self.client.get(url, params or {})
        self.assertEqual(response.status_code, 200)
        return response

    def append(self, token, objects):
        """
        Submit one continuation through the shared Search and My Data action

        Parameters
        ----------
        token : str or list of str
            Navigation token, including deliberately invalid test values.
        objects : list of JSONData
            Requested complete batch.

        Returns
        -------
        HttpResponse
            Mutation result.
        """
        return self.client.post(reverse("graph_selection_create"), {
            "graph_context": token, "selected_objects": [obj.pk for obj in objects],
        })

    def test_temporary_continuation_unions_into_same_session_entry(self):
        """
        Preserve the original selection URL and deduplicate existing records
        """
        workspace = self.workspace(selection=True)
        token = workspace.context["graph_context"]
        selection_token = workspace.context["selection_token"]
        original_path = workspace.context["workspace_url"]
        response = self.append(token, [self.public, self.owned, self.second, self.public])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, original_path)
        selections = self.client.session[SELECTION_SESSION_KEY]
        self.assertEqual(list(selections), [selection_token])
        self.assertEqual(selections[selection_token]["objects"], [self.owned.pk, self.public.pk, self.second.pk])
        self.assertContains(self.client.get(response.url), "Selected objects added to this selection.")

    def test_saved_continuation_adds_directly_without_creating_a_selection(self):
        """
        Append all requested accessible records and retain original raw metadata
        """
        workspace = self.workspace()
        response = self.append(workspace.context["graph_context"], [self.owned, self.public, self.shared])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.collection.members.values_list("pk", flat=True)),
                         {self.owned.pk, self.public.pk, self.shared.pk})
        self.assertNotIn(SELECTION_SESSION_KEY, self.client.session)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.data["identifier"], "navigation-owned")
        self.assertContains(self.client.get(response.url), "Selected objects added to the collection.")
        duplicate = self.append(workspace.context["graph_context"], [self.owned])
        self.assertContains(self.client.get(duplicate.url), "already in this collection")

    def test_empty_and_inaccessible_collections_can_continue_selection(self):
        """
        Keep empty workspaces usable without dereferencing an absent graph
        """
        for members in ([], [self.hidden]):
            with self.subTest(members=members):
                self.collection.members.set(members)
                workspace = self.workspace()
                self.assertIsNone(workspace.context["relationship_graph"])
                self.assertTrue(workspace.context["graph_continue_search_url"])
                response = self.append(workspace.context["graph_context"], [self.public])
                self.assertEqual(response.status_code, 302)
                self.assertIn(self.public, self.collection.members.all())
                self.assertNotContains(workspace, self.hidden.data["title"])

    def test_invalid_requested_member_rejects_whole_batch_in_original_scope(self):
        """
        Keep the collection unchanged and its original view visible after a failure
        """
        workspace = self.workspace(params={"links": "software", "view": "detailed"})
        group = workspace.context["group_options"][0]["key"]
        workspace = self.workspace(params={"links": "software", "group": group, "view": "detailed"})
        response = self.append(workspace.context["graph_context"], [self.public, self.hidden])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.collection.members.values_list("pk", flat=True)), [self.owned.pk])
        self.assertEqual(response.context["links_mode"], "software")
        self.assertEqual(response.context["selected_group"]["key"], group)
        self.assertEqual(response.context["graph_view_mode"], "detailed")
        self.assertNotContains(response, self.hidden.data["title"], status_code=400)

    def test_temporary_union_capacity_and_bad_member_preserve_original_selection(self):
        """
        Check the complete combined selection before writing any session state
        """
        workspace = self.workspace(selection=True, objects=[self.owned, self.public])
        token = workspace.context["graph_context"]
        original = self.client.session[SELECTION_SESSION_KEY]
        with patch("apps.pages.research_collections.MAX_SELECTION_OBJECTS", 2):
            response = self.append(token, [self.second])
        self.assertContains(response, "Save this selection as a research collection", status_code=400)
        self.assertEqual(self.client.session[SELECTION_SESSION_KEY], original)
        self.assertEqual(self.append(token, [self.second, self.hidden]).status_code, 400)
        self.assertEqual(self.client.session[SELECTION_SESSION_KEY], original)

    def test_saved_capacity_counts_retained_inaccessible_references(self):
        """
        Reject overcapacity additions without revealing or removing hidden members
        """
        self.collection.members.add(self.hidden)
        workspace = self.workspace()
        with patch("apps.pages.research_collections.MAX_COLLECTION_OBJECTS", 2):
            response = self.append(workspace.context["graph_context"], [self.public])
        self.assertContains(response, "clear unavailable members", status_code=400)
        self.assertEqual(set(self.collection.members.values_list("pk", flat=True)),
                         {self.owned.pk, self.hidden.pk})
        self.assertNotContains(response, self.hidden.data["title"], status_code=400)

    def test_original_selection_access_is_rechecked_before_union(self):
        """
        Refuse additions after an existing share is revoked without dropping it silently
        """
        workspace = self.workspace(selection=True, objects=[self.owned, self.shared])
        original = self.client.session[SELECTION_SESSION_KEY]
        self.shared.shared_users.clear()
        stale_workspace = self.client.get(workspace.context["workspace_url"])
        self.assertContains(stale_workspace, "Some selected objects are unavailable")
        self.assertContains(stale_workspace, "Start a new selection")
        self.assertNotContains(stale_workspace, 'id="collection-select-more"')
        self.assertNotContains(stale_workspace, self.shared.data["title"])
        response = self.append(workspace.context["graph_context"], [self.public])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session[SELECTION_SESSION_KEY], original)
        self.assertNotContains(response, self.shared.data["title"], status_code=400)

    def test_tampered_empty_and_repeated_tokens_never_create_new_selection(self):
        """
        Reject invalid continuation even when all selected objects are accessible
        """
        token = self.workspace().context["graph_context"]
        for submitted in (token + "x", "", [token, token], [token, ""]):
            with self.subTest(submitted=submitted):
                self.assertEqual(self.append(submitted, [self.public]).status_code, 400)
                self.assertNotIn(SELECTION_SESSION_KEY, self.client.session)
                self.assertEqual(self.collection.members.count(), 1)
        for query_token in (token, "bad-token"):
            response = self.client.post(reverse("graph_selection_create") + "?graph_context=" + query_token, {
                "selected_objects": [self.public.pk],
            })
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(SELECTION_SESSION_KEY, self.client.session)

    def test_view_tokens_change_only_the_original_workspace_presentation(self):
        """
        Supply independently signed modes for immediate client side view changes
        """
        workspace = self.workspace(params={"links": "software"})
        original = signing.loads(workspace.context["graph_context"], salt=CONTEXT_SALT)
        for view in ("compact", "detailed"):
            payload = signing.loads(workspace.context[f"graph_context_{view}"], salt=CONTEXT_SALT)
            self.assertEqual(payload, {**original, "params": {**original["params"], "view": view}})

    def test_cross_user_context_does_not_disclose_collection_on_public_object(self):
        """
        Keep public object access while discarding another user's private navigation
        """
        token = self.workspace().context["graph_context"]
        payload = signing.loads(token, salt=CONTEXT_SALT)
        self.assertNotIn(self.collection.title, str(payload))
        self.client.force_login(self.other)
        for name, params in (("json_data_detail", {}), ("graph", {"object": self.public.pk})):
            url = reverse(name, args=[self.public.pk]) if name == "json_data_detail" else reverse(name)
            response = self.client.get(url, {**params, "graph_context": token})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["graph_navigation_error"])
            self.assertEqual(response.context["graph_return_url"], "")
            self.assertEqual(response.context["graph_context"], "")
            self.assertNotContains(response, self.collection.title)
        self.assertEqual(self.append(token, [self.public]).status_code, 400)
        self.assertEqual(self.collection.members.count(), 1)

    def test_collection_owner_and_token_age_are_rechecked(self):
        """
        Reject a once valid continuation after ownership changes or expiry
        """
        token = self.workspace().context["graph_context"]
        future = time.time() + CONTEXT_MAX_AGE + 2
        with patch("django.core.signing.time.time", return_value=future):
            self.assertEqual(self.append(token, [self.public]).status_code, 400)
        self.collection.owner = self.other
        self.collection.save(update_fields=["owner"])
        response = self.client.get(reverse("search"), {"graph_context": token, "keyword": "copper"})
        self.assertTrue(response.context["graph_navigation_error"])
        self.assertNotContains(response, self.collection.title)
        self.assertEqual(self.append(token, [self.public]).status_code, 400)

    def test_temporary_context_requires_original_session_and_entry(self):
        """
        Prevent copied or evicted temporary selections from becoming unrelated selections
        """
        workspace = self.workspace(selection=True)
        token = workspace.context["graph_context"]
        second_browser = Client()
        second_browser.force_login(self.owner)
        response = second_browser.post(reverse("graph_selection_create"), {
            "graph_context": token, "selected_objects": [self.public.pk],
        })
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(SELECTION_SESSION_KEY, second_browser.session)
        session = self.client.session
        session[SELECTION_SESSION_KEY] = {}
        session.save()
        self.assertEqual(self.append(token, [self.public]).status_code, 400)
        self.assertEqual(self.client.session[SELECTION_SESSION_KEY], {})

    def test_return_scope_and_object_links_retain_group_pages_and_view(self):
        """
        Return from detail and standalone Graph to the same canonical collection page
        """
        records = JSONData.objects.bulk_create([
            JSONData(owner=self.owner, data={"title": f"Copper variant {index}", "software": "DAMASK"})
            for index in range(27)
        ])
        self.collection.members.add(*records)
        workspace = self.workspace(params={"links": "software"})
        group = workspace.context["group_options"][0]["key"]
        workspace = self.workspace(params={
            "links": "software", "group": group, "page": "2", "groups_page": "1", "view": "detailed",
        })
        expected = workspace.context["graph_return_url"]
        query = parse_qs(urlsplit(expected).query)
        self.assertEqual(query, {"links": ["software"], "group": [group], "page": ["2"],
                                 "groups_page": ["1"], "view": ["detailed"]})
        row = workspace.context["object_rows"][0]
        node = next(node for node in workspace.context["relationship_graph"]["nodes"]
                    if node["id"] == f"collection-object-{row['pk']}")
        self.assertEqual(node["source_url"], row["detail_url"])
        self.assertEqual(node["graph_url"], row["graph_url"])
        response = self.client.get(row["graph_url"])
        for key in ("graph_detail_url", "graph_detail_graph_url", "graph_standalone_url",
                    "graph_compact_url", "graph_detailed_url"):
            linked = self.client.get(response.context[key])
            self.assertEqual(linked.status_code, 200)
            self.assertEqual(linked.context["graph_return_url"], expected)
        added = self.append(workspace.context["graph_context"], [self.second])
        self.assertEqual(added.url, expected)

    def test_context_only_search_and_filter_queries_keep_existing_semantics(self):
        """
        Carry navigation without turning it into a search condition or widening filters
        """
        workspace = self.workspace()
        token = workspace.context["graph_context"]
        empty = self.client.get(workspace.context["graph_continue_search_url"])
        self.assertFalse(empty.context["search_performed"])
        plain = self.client.get(reverse("search"), {"keyword": "copper", "software": "DAMASK"})
        continued = self.client.get(reverse("search"), {
            "keyword": "copper", "software": "DAMASK", "graph_context": token,
        })
        self.assertEqual(continued.context["result_count"], plain.context["result_count"])
        self.assertEqual(continued.context["keyword"], "copper")
        self.assertEqual(continued.context["graph_add_label"], f"Add to {self.collection.title}")
        params = {"software": "ABAQUS", "graph_context": token}
        filtered = self.client.get(reverse("json_data_list"), params)
        self.assertEqual([obj.pk for obj in filtered.context["data_objects"]], [self.second.pk])
        self.assertEqual(filtered.context["graph_context"], token)

    def test_signed_payload_cannot_supply_an_arbitrary_destination(self):
        """
        Reject unknown or malformed return arguments even in a correctly signed payload
        """
        token = self.workspace().context["graph_context"]
        original = signing.loads(token, salt=CONTEXT_SALT)
        for params in ({"next": "https://example.invalid"}, {"group": "//example.invalid"},
                       {"links": ["members"]}, {"page": "-1"}, {"links": "members", "group": "missing"}):
            with self.subTest(params=params):
                payload = {**original, "params": params}
                forged = signing.dumps(payload, salt=CONTEXT_SALT)
                self.assertEqual(self.append(forged, [self.public]).status_code, 400)
        self.assertEqual(self.collection.members.count(), 1)

    def test_context_gets_never_change_collection_or_temporary_members(self):
        """
        Keep browsing and return navigation free of membership mutations
        """
        workspace = self.workspace(selection=True)
        original = self.client.session[SELECTION_SESSION_KEY]
        token = workspace.context["graph_context"]
        for name in ("search", "json_data_list"):
            self.client.get(reverse(name), {"graph_context": token, "selected_objects": [self.public.pk]})
        self.client.get(reverse("graph_selection_create"), {
            "graph_context": token, "selected_objects": [self.public.pk],
        })
        self.assertEqual(self.client.session[SELECTION_SESSION_KEY], original)
        self.assertEqual(list(self.collection.members.values_list("pk", flat=True)), [self.owned.pk])
