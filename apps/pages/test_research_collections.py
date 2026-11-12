"""
Check collection ownership, complete selection validation and permission changes
"""

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.urls import path, reverse

from . import research_collections as views
from .models import JSONData, ResearchCollection


urlpatterns = [
    path("graph/collections/", views.collection_index, name="collection_index"),
    path("graph/selection/", views.selection_create, name="graph_selection_create"),
    path("graph/selection/<str:token>/", views.selection_detail, name="selection_detail"),
    path("graph/selection/<str:token>/save/", views.collection_save, name="collection_save"),
    path("graph/selection/<str:token>/add/", views.collection_add, name="collection_add"),
    path("graph/selection/<str:token>/export/", views.selection_export, name="selection_export"),
    path("graph/collections/<int:pk>/", views.collection_detail, name="collection_detail"),
    path("graph/collections/<int:pk>/edit/", views.collection_update, name="collection_update"),
    path("graph/collections/<int:pk>/remove/", views.collection_remove, name="collection_remove"),
    path("graph/collections/<int:pk>/clear-unavailable/", views.collection_cleanup, name="collection_cleanup"),
    path("graph/collections/<int:pk>/delete/", views.collection_delete, name="collection_delete"),
    path("graph/collections/<int:pk>/export/", views.collection_export, name="collection_export"),
]

TEST_TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "OPTIONS": {"loaders": [("django.template.loaders.locmem.Loader", {
        "pages/collections.html": "{{ selection_error }}{% for collection in collections %}{{ collection.title }}:{{ collection.visible_count }}{% endfor %}",
        "pages/collection_graph.html": "{{ selection_error }}{{ collection_form.errors }}{% for row in object_rows %}{{ row.title }}{% endfor %}",
    })]},
}]


def graph_context(objects, *, title, base_url, params):
    """
    Isolate graph rendering while observing exactly which records reach it

    Parameters
    ----------
    objects : QuerySet
        Permission restricted records supplied by the view.
    title : str
        Workspace title.
    base_url : str
        Workspace URL.
    params : QueryDict
        Requested display options.

    Returns
    -------
    dict
        Minimal graph context retaining record identities and supplied titles.
    """
    rows = []
    for obj in objects.order_by("pk"):
        rows.append({"pk": obj.pk, "title": obj.data.get("title", "")})
    return {"object_rows": rows, "object_total": len(rows)}


@override_settings(ROOT_URLCONF=__name__, TEMPLATES=TEST_TEMPLATES)
class ResearchCollectionTests(TestCase):
    """
    Keep private collection membership separate from individual record access
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create owned, public, shared and inaccessible records
        """
        cls.owner = User.objects.create_user(username="collection-owner")
        cls.other = User.objects.create_user(username="collection-other")
        cls.owned = JSONData.objects.create(owner=cls.owner, data={
            "title": "Owned simulation", "Identifier": ["original-id"],
            "Stress": {"stress_11": [0, 1.123456789, -2]}, "extra": False,
        })
        cls.public = JSONData.objects.create(owner=cls.other, access_type="all", data={"title": "Public simulation"})
        cls.shared = JSONData.objects.create(owner=cls.other, data={"title": "Shared simulation"})
        cls.shared.shared_users.add(cls.owner)
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "Secret unrelated simulation"})

    def setUp(self):
        """
        Sign in and replace only the independent graph renderer
        """
        self.client.force_login(self.owner)
        self.graph_patch = patch("apps.pages.research_collections._graph_context", side_effect=graph_context)
        self.graph_patch.start()
        self.addCleanup(self.graph_patch.stop)

    def selection(self, objects=None):
        """
        Create a temporary workspace through its public POST endpoint

        Parameters
        ----------
        objects : list of JSONData or None, optional
            Records to select, defaulting to the viewer's own record.

        Returns
        -------
        str
            Session selection token returned through the redirect.
        """
        objects = [self.owned] if objects is None else objects
        response = self.client.post(reverse("graph_selection_create"), {"selected_objects": [obj.pk for obj in objects]})
        self.assertEqual(response.status_code, 302)
        return response.url.rstrip("/").split("/")[-1]

    def collection(self, objects=None, owner=None, title="Parameter study"):
        """
        Prepare a saved collection without bypassing view tests for mutations

        Parameters
        ----------
        objects : list of JSONData or None, optional
            Initial membership.
        owner : User or None, optional
            Collection owner, defaulting to the signed-in user.
        title : str, optional
            Collection title.

        Returns
        -------
        ResearchCollection
            Saved collection fixture.
        """
        collection = ResearchCollection.objects.create(owner=owner or self.owner, title=title)
        collection.members.add(*(objects if objects is not None else [self.owned]))
        return collection

    def test_selection_accepts_owned_public_shared_and_deduplicates(self):
        """
        Keep selection temporary and include each accessible object once
        """
        token = self.selection([self.owned, self.public, self.shared, self.owned])
        self.assertFalse(ResearchCollection.objects.exists())
        response = self.client.get(reverse("selection_detail", args=[token]))
        self.assertEqual(response.context["object_total"], 3)
        self.assertEqual({row["pk"] for row in response.context["object_rows"]}, {self.owned.pk, self.public.pk, self.shared.pk})
        self.assertNotContains(response, self.hidden.data["title"])

    def test_invalid_or_partly_inaccessible_selection_never_saves_partial_workset(self):
        """
        Reject missing, malformed and inaccessible IDs before writing the session
        """
        invalid = ["0", "-1", "1.0", " 1", "+1", "١", "9223372036854775808", "9" * 30, str(self.hidden.pk), "999999"]
        for value in invalid:
            with self.subTest(value=value):
                response = self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.owned.pk, value]})
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, self.hidden.data["title"], status_code=400)
                self.assertFalse(self.client.session.get(views.SELECTION_SESSION_KEY))
        self.assertEqual(self.client.post(reverse("graph_selection_create")).status_code, 400)

    def test_selection_limit_is_checked_before_access_queries(self):
        """
        Bound submitted selections independently of the saved collection limit
        """
        response = self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.owned.pk] * 501})
        self.assertContains(response, "Select up to 500", status_code=400)
        self.assertFalse(self.client.session.get(views.SELECTION_SESSION_KEY))

    def test_selection_requires_the_original_authenticated_session(self):
        """
        Opaque temporary URLs do not expose data to another user or browser
        """
        token = self.selection()
        url = reverse("selection_detail", args=[token])
        second_browser = Client()
        second_browser.force_login(self.owner)
        self.assertEqual(second_browser.get(url).status_code, 404)
        session = self.client.session
        entries = session[views.SELECTION_SESSION_KEY]
        entries[token]["owner"] = self.other.pk
        session[views.SELECTION_SESSION_KEY] = entries
        session.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("selection_detail", args=["bad-token"])).status_code, 404)

    def test_temporary_worksets_evict_oldest_after_eight(self):
        """
        Bound session growth while preserving the most recent worksets
        """
        tokens = [self.selection() for _ in range(9)]
        self.assertEqual(len(self.client.session[views.SELECTION_SESSION_KEY]), 8)
        self.assertEqual(self.client.get(reverse("selection_detail", args=[tokens[0]])).status_code, 404)
        self.assertEqual(self.client.get(reverse("selection_detail", args=[tokens[-1]])).status_code, 200)

    def test_save_preserves_json_permissions_and_trimmed_collection_details(self):
        """
        Store membership without rewriting records or expanding their visibility
        """
        original = self.owned.data.copy()
        token = self.selection([self.owned, self.public, self.shared])
        response = self.client.post(reverse("collection_save", args=[token]), {"title": "  Cyclic study  ", "description": "  Shared research context  "})
        self.assertEqual(response.status_code, 302)
        collection = ResearchCollection.objects.get()
        self.assertEqual(collection.owner, self.owner)
        self.assertEqual(collection.title, "Cyclic study")
        self.assertEqual(collection.description, "Shared research context")
        self.assertEqual(collection.members.count(), 3)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.data, original)
        self.assertEqual(self.owned.access_type, "c")
        self.assertEqual(list(self.shared.shared_users.all()), [self.owner])

    def test_save_validates_title_description_and_duplicate_fields(self):
        """
        Return editable errors without creating incomplete collections
        """
        token = self.selection()
        invalid_forms = [
            {"title": "  "}, {"title": "x" * 201},
            {"title": "Study", "description": "x" * 2001},
            {"title": ["One", "Two"]}, {"title": "Study", "description": ["One", "Two"]},
        ]
        for form in invalid_forms:
            with self.subTest(form=str(form)[:50]):
                response = self.client.post(reverse("collection_save", args=[token]), form)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.context["collection_form"].errors)
                self.assertFalse(ResearchCollection.objects.exists())

    def test_revoked_selection_hides_metadata_and_rejects_save_and_export(self):
        """
        Recheck membership visibility without silently saving a partial selection
        """
        token = self.selection([self.owned, self.shared])
        self.shared.shared_users.clear()
        response = self.client.get(reverse("selection_detail", args=[token]))
        self.assertEqual(response.context["object_total"], 1)
        self.assertNotContains(response, "Shared simulation")
        saved = self.client.post(reverse("collection_save", args=[token]), {"title": "Do not partially save"})
        self.assertEqual(saved.status_code, 400)
        self.assertFalse(ResearchCollection.objects.exists())
        exported = self.client.get(reverse("selection_export", args=[token]))
        self.assertEqual(exported.status_code, 400)

    def test_collection_index_and_graph_count_only_accessible_members(self):
        """
        Exclude revoked records from counts and all graph context
        """
        collection = self.collection([self.owned, self.public, self.shared])
        self.shared.shared_users.clear()
        self.public.access_type = "c"
        self.public.save(update_fields=["access_type"])
        self.collection([self.hidden], owner=self.other, title="Hidden collection title")
        response = self.client.get(reverse("collection_index"))
        self.assertEqual(list(response.context["collections"])[0].visible_count, 1)
        self.assertNotContains(response, "Hidden collection title")
        graph = self.client.get(reverse("collection_detail", args=[collection.pk]))
        self.assertEqual(graph.context["object_total"], 1)
        self.assertNotContains(graph, "Shared simulation")
        self.assertNotContains(graph, "Public simulation")

    def test_foreign_collection_routes_and_add_target_are_not_accessible(self):
        """
        Enforce collection ownership in every server endpoint
        """
        collection = self.collection([self.public], owner=self.other)
        for name in ("collection_detail", "collection_export"):
            self.assertEqual(self.client.get(reverse(name, args=[collection.pk])).status_code, 404)
        for name in ("collection_update", "collection_remove", "collection_cleanup", "collection_delete"):
            response = self.client.post(reverse(name, args=[collection.pk]), {"title": "Changed", "selected_objects": [self.public.pk]})
            self.assertEqual(response.status_code, 404)
        token = self.selection()
        self.assertEqual(self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk}).status_code, 404)
        collection.refresh_from_db()
        self.assertEqual(collection.title, "Parameter study")
        self.assertEqual(list(collection.members.all()), [self.public])

    def test_add_selection_is_idempotent_and_objects_can_belong_to_multiple_collections(self):
        """
        Add complete selections without duplicating membership or moving records
        """
        first = self.collection()
        second = self.collection([], title="Second study")
        token = self.selection([self.owned, self.public])
        for collection in (first, first, second):
            response = self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(collection.members.count(), 2)
        self.assertEqual(self.owned.research_collections.count(), 2)

    def test_add_rechecks_access_and_rejects_all_members_after_revocation(self):
        """
        Leave the destination unchanged if one selected record lost access
        """
        collection = self.collection([])
        token = self.selection([self.public, self.shared])
        self.shared.shared_users.clear()
        response = self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(collection.members.count(), 0)

    def test_add_checks_full_collection_limit_before_any_membership_change(self):
        """
        Allow exactly one thousand members and reject an overflowing batch atomically
        """
        records = JSONData.objects.bulk_create([JSONData(owner=self.owner, data={}) for _ in range(999)])
        collection = self.collection(records)
        token = self.selection([self.owned, self.public])
        response = self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(collection.members.count(), 999)
        token = self.selection([self.owned])
        self.assertEqual(self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk}).status_code, 302)
        self.assertEqual(collection.members.count(), 1000)

    def test_add_rejects_repeated_or_malformed_target(self):
        """
        Never choose between conflicting collection IDs
        """
        collection = self.collection([])
        token = self.selection()
        for value in ([collection.pk, collection.pk], "-1", "١", "9223372036854775808", ""):
            response = self.client.post(reverse("collection_add", args=[token]), {"collection_id": value})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(collection.members.count(), 0)

    def test_clearing_unavailable_members_restores_full_collection_capacity(self):
        """
        Recover a full collection when every member has become inaccessible
        """
        records = JSONData.objects.bulk_create([
            JSONData(owner=self.other, data={"title": "Unavailable run"}) for _ in range(1000)
        ])
        collection = self.collection(records)
        token = self.selection()
        blocked = self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk})
        self.assertEqual(blocked.status_code, 400)
        self.assertContains(blocked, "use Edit collection to clear unavailable members", status_code=400)
        self.assertEqual(self.client.get(reverse("collection_detail", args=[collection.pk])).context["object_total"], 0)
        response = self.client.post(f"/graph/collections/{collection.pk}/clear-unavailable/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(collection.members.count(), 0)
        added = self.client.post(reverse("collection_add", args=[token]), {"collection_id": collection.pk})
        self.assertEqual(added.status_code, 302)
        self.assertEqual(list(collection.members.all()), [self.owned])
        self.assertEqual(JSONData.objects.filter(pk__in=[obj.pk for obj in records]).count(), 1000)

    def test_cleanup_preserves_accessible_members_and_all_original_records(self):
        """
        Clear only unavailable references while retaining owned, public and shared members
        """
        revoked = JSONData.objects.create(owner=self.other, data={"title": "Revoked private title", "secret": [3, 2, 1]})
        revoked.shared_users.add(self.owner)
        collection = self.collection([self.owned, self.public, self.shared, revoked])
        original = list(JSONData.objects.order_by("pk").values("pk", "owner_id", "data", "access_type"))
        revoked.shared_users.clear()
        original_shares = list(JSONData.shared_users.through.objects.order_by("pk").values())
        response = self.client.post(reverse("collection_cleanup", args=[collection.pk]), {"selected_objects": [self.owned.pk, self.public.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(collection.members.values_list("pk", flat=True)), {self.owned.pk, self.public.pk, self.shared.pk})
        self.assertEqual(list(JSONData.objects.order_by("pk").values("pk", "owner_id", "data", "access_type")), original)
        self.assertEqual(list(JSONData.shared_users.through.objects.order_by("pk").values()), original_shares)
        self.assertEqual([str(message) for message in get_messages(response.wsgi_request)], [
            "Unavailable members cleared. Data objects are unchanged.",
        ])
        self.assertNotIn("Revoked private title", response.content.decode())
        collection.refresh_from_db()
        self.assertGreater(collection.updated_at, collection.created_at)

    def test_cleanup_acknowledgement_is_the_same_for_zero_or_many_unavailable_members(self):
        """
        Avoid exposing whether a collection contained hidden member references
        """
        for objects in ([], [self.owned], [self.hidden, self.owned]):
            with self.subTest(member_count=len(objects)):
                collection = self.collection(objects)
                response = self.client.post(reverse("collection_cleanup", args=[collection.pk]))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.content, b"")
                messages = [str(message) for message in get_messages(response.wsgi_request)]
                self.assertEqual(messages[-1], "Unavailable members cleared. Data objects are unchanged.")
                self.assertNotIn("Secret", str(messages))
                self.assertEqual(collection.members.count(), int(self.owned in objects))

    def test_remove_rejects_mixed_membership_without_partial_removal(self):
        """
        Keep all members when any submitted ID is invalid or not in this collection
        """
        collection = self.collection([self.owned, self.shared])
        for value in (self.public.pk, self.hidden.pk, "bad"):
            response = self.client.post(reverse("collection_remove", args=[collection.pk]), {"selected_objects": [self.owned.pk, value]})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(collection.members.count(), 2)
        response = self.client.post(reverse("collection_remove", args=[collection.pk]), {"selected_objects": [self.owned.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(collection.members.all()), [self.shared])
        self.assertTrue(JSONData.objects.filter(pk=self.owned.pk).exists())

    def test_update_validation_and_delete_never_change_data_objects(self):
        """
        Rename or delete collection metadata while retaining the original records
        """
        collection = self.collection()
        response = self.client.post(reverse("collection_update", args=[collection.pk]), {"title": " "})
        self.assertEqual(response.status_code, 400)
        collection.refresh_from_db()
        self.assertEqual(collection.title, "Parameter study")
        response = self.client.post(reverse("collection_update", args=[collection.pk]), {"title": "Renamed", "description": "Context"})
        self.assertEqual(response.status_code, 302)
        collection.refresh_from_db()
        self.assertEqual((collection.title, collection.description), ("Renamed", "Context"))
        self.assertEqual(self.client.post(reverse("collection_delete", args=[collection.pk])).status_code, 302)
        self.assertFalse(ResearchCollection.objects.exists())
        self.assertTrue(JSONData.objects.filter(pk=self.owned.pk).exists())

    def test_deleting_a_record_removes_membership_and_hides_stale_workset_entry(self):
        """
        Handle records deleted after a selection or collection was created
        """
        collection = self.collection([self.owned, self.shared])
        token = self.selection([self.owned, self.shared])
        self.shared.delete()
        response = self.client.get(reverse("selection_detail", args=[token]))
        self.assertEqual(response.context["object_total"], 1)
        self.assertEqual(collection.members.count(), 1)
        self.assertEqual(self.client.post(reverse("collection_save", args=[token]), {"title": "Stale"}).status_code, 400)

    def test_json_exports_preserve_original_values_and_omit_revoked_collection_members(self):
        """
        Export original records without collection metadata or hidden record information
        """
        collection = self.collection([self.owned, self.shared])
        self.shared.shared_users.clear()
        response = self.client.get(reverse("collection_export", args=[collection.pk]))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(b"".join(response.streaming_content))
        self.assertEqual(payload, [self.owned.data])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        token = self.selection([self.owned, self.public])
        response = self.client.get(reverse("selection_export", args=[token]))
        self.assertEqual(json.loads(b"".join(response.streaming_content)), [self.owned.data, self.public.data])

    def test_empty_collection_is_valid_and_exports_an_empty_array(self):
        """
        Keep saved collection metadata usable after all members are removed
        """
        collection = self.collection([])
        response = self.client.get(reverse("collection_detail", args=[collection.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object_total"], 0)
        exported = self.client.get(reverse("collection_export", args=[collection.pk]))
        self.assertEqual(json.loads(b"".join(exported.streaming_content)), [])

    def test_invalid_graph_group_does_not_broaden_results(self):
        """
        Return an empty error context when the graph rejects a grouping condition
        """
        collection = self.collection()
        with patch("apps.pages.research_collections._graph_context", side_effect=ValueError("Choose a valid relationship group.")):
            response = self.client.get(reverse("collection_detail", args=[collection.pk]), {"group": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context["object_rows"], [])
        self.assertEqual(response.context["object_total"], 0)
        self.assertNotContains(response, self.owned.data["title"], status_code=400)

    def test_index_paginates_and_filters_only_owned_collections(self):
        """
        Keep long private collection lists bounded and searchable
        """
        ResearchCollection.objects.bulk_create([ResearchCollection(owner=self.owner, title=f"Study {i}") for i in range(27)])
        self.collection(owner=self.other, title="Study secret")
        response = self.client.get(reverse("collection_index"))
        self.assertEqual(len(response.context["collections"]), 25)
        self.assertEqual(response.context["collection_page"].paginator.count, 27)
        self.assertEqual(len(self.client.get(reverse("collection_index"), {"page": 2}).context["collections"]), 2)
        response = self.client.get(reverse("collection_index"), {"q": "Study 26"})
        self.assertEqual(len(response.context["collections"]), 1)

    def test_mutations_require_post_and_csrf_and_all_routes_require_login(self):
        """
        Reject state changes through GET and unprotected cross-site form submissions
        """
        token = self.selection()
        collection = self.collection()
        mutations = [
            reverse("graph_selection_create"), reverse("collection_save", args=[token]),
            reverse("collection_add", args=[token]), reverse("collection_update", args=[collection.pk]),
            reverse("collection_remove", args=[collection.pk]), reverse("collection_cleanup", args=[collection.pk]),
            reverse("collection_delete", args=[collection.pk]),
        ]
        for url in mutations:
            self.assertEqual(self.client.get(url).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        self.assertEqual(protected.post(reverse("graph_selection_create"), {"selected_objects": [self.owned.pk]}).status_code, 403)
        self.assertEqual(protected.post(reverse("collection_cleanup", args=[collection.pk])).status_code, 403)
        self.client.logout()
        for url in mutations + [reverse("collection_index"), reverse("collection_detail", args=[collection.pk]), reverse("selection_detail", args=[token]), reverse("collection_export", args=[collection.pk]), reverse("selection_export", args=[token])]:
            self.assertEqual(self.client.get(url).status_code, 302)


class ResearchCollectionIntegrationTests(TestCase):
    """
    Exercise real routes, graph summaries and templates through the full workflow
    """

    def setUp(self):
        """
        Create two accessible simulations that declare the same reference
        """
        self.owner = User.objects.create_user(username="collection-integration-owner")
        self.other = User.objects.create_user(username="collection-integration-other")
        self.first = JSONData.objects.create(owner=self.owner, data={
            "title": "First parameter run", "identifier": "first-run", "software": "DAMASK",
            "phase": [{"phase_name": "Copper"}], "relation": ["10.1000/parameter-study"],
        })
        self.second = JSONData.objects.create(owner=self.other, data={
            "title": "Restricted parameter run", "identifier": "restricted-run", "software": "DAMASK",
            "phase": [{"phase_name": "Copper"}], "relation": ["10.1000/parameter-study"],
        })
        self.second.shared_users.add(self.owner)
        self.client.force_login(self.owner)

    def test_select_save_browse_group_and_open_single_object(self):
        """
        Keep the approved workflow usable with ordinary forms and native links
        """
        selected = self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.first.pk, self.second.pk]})
        self.assertEqual(selected.status_code, 302)
        response = self.client.get(selected.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object_total"], 2)
        self.assertContains(response, "Save collection")
        token = response.context["selection_token"]
        saved = self.client.post(reverse("collection_save", args=[token]), {"title": "Copper parameter study"})
        self.assertEqual(saved.status_code, 302)
        response = self.client.get(saved.url)
        self.assertContains(response, "Copper parameter study")
        groups = response.context["group_options"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 2)
        grouped = self.client.get(groups[0]["url"])
        self.assertEqual(grouped.status_code, 200)
        self.assertEqual(grouped.context["matching_object_count"], 2)
        row = grouped.context["object_rows"][0]
        detail = self.client.get(row["graph_url"])
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Node details")

    def test_real_graph_and_group_links_do_not_expose_revoked_members(self):
        """
        Exclude hidden members from the actual graph, count labels and object table
        """
        collection = ResearchCollection.objects.create(owner=self.owner, title="Visible study")
        collection.members.add(self.first, self.second)
        self.second.shared_users.clear()
        response = self.client.get(reverse("collection_detail", args=[collection.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object_total"], 1)
        self.assertNotContains(response, "Restricted parameter run")
        self.assertNotContains(response, "restricted-run")
        self.assertEqual(response.context["group_options"][0]["count"], 1)
        group = self.client.get(response.context["group_options"][0]["url"])
        self.assertEqual(len(group.context["object_rows"]), 1)
        self.assertNotContains(group, "Restricted parameter run")
        invalid = self.client.get(reverse("collection_detail", args=[collection.pk]), {"group": "unrecognized"})
        self.assertEqual(invalid.status_code, 400)
        self.assertNotContains(invalid, "First parameter run", status_code=400)

    def test_invalid_group_can_return_to_the_same_workspace_without_a_false_empty_state(self):
        """
        Let saved and temporary selections recover from an unavailable group
        """
        collection = ResearchCollection.objects.create(owner=self.owner, title="Recoverable study")
        collection.members.add(self.first)
        selected = self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.first.pk]})
        for url in (reverse("collection_detail", args=[collection.pk]), selected.url):
            response = self.client.get(url, {"group": "stale"})
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, f'href="{url}" id="collection-reset-view"', status_code=400)
            self.assertNotContains(response, "0 accessible data objects", status_code=400)
            self.assertNotContains(response, "No accessible data objects", status_code=400)
            self.assertNotContains(response, "First parameter run", status_code=400)
            recovered = self.client.get(url)
            self.assertEqual(recovered.status_code, 200)
            self.assertEqual(recovered.context["object_total"], 1)
