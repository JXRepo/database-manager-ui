"""
Check private user supplied collection relationships through their HTTP endpoints
"""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from .collection_relationships import MAX_COLLECTION_RELATIONSHIPS, accessible_relationships
from . import collection_relationships as relationship_views
from . import research_collections as collection_views
from .models import CollectionRelationship, JSONData, ResearchCollection


class CollectionRelationshipTests(TestCase):
    """
    Keep manual links private, explicit and separate from original records
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create two accessible members in a private collection
        """
        cls.owner = User.objects.create_user(username="relationship-owner")
        cls.other = User.objects.create_user(username="relationship-other")
        cls.source = JSONData.objects.create(owner=cls.owner, data={"title": "Source simulation", "identifier": "source-original", "extra": [0, False]})
        cls.target = JSONData.objects.create(owner=cls.owner, data={"title": "Target simulation", "identifier": "target-original"})
        cls.public = JSONData.objects.create(owner=cls.other, access_type="all", data={"title": "Public simulation", "identifier": "public-original"})
        cls.shared = JSONData.objects.create(owner=cls.other, data={"title": "Shared simulation"})
        cls.shared.shared_users.add(cls.owner)
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "Secret simulation title", "identifier": "secret-identifier"})
        cls.outside = JSONData.objects.create(owner=cls.owner, data={"title": "Outside collection"})
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Comparison")
        cls.collection.members.add(cls.source, cls.target, cls.public, cls.shared)
        cls.foreign_collection = ResearchCollection.objects.create(owner=cls.other, title="Other owner's private collection")
        cls.foreign_collection.members.add(cls.public, cls.hidden)

    def setUp(self):
        """
        Sign in as the private collection's owner
        """
        self.client.force_login(self.owner)

    def save(self, *, collection=None, **changes):
        """
        Submit the normal endpoint with explicit JSON feedback

        Parameters
        ----------
        collection : ResearchCollection or None, optional
            Target collection, defaulting to the owned fixture.
        **changes : object
            Overrides for source, target, label and edit version.

        Returns
        -------
        HttpResponse
            Actual view response.
        """
        fields = {"source": self.source.pk, "target": self.target.pk, "label": "Compared with", **changes}
        return self.client.post(
            reverse("collection_relationship_save", args=[(collection or self.collection).pk]),
            fields, HTTP_ACCEPT="application/json",
        )

    def link(self, *, collection=None, source=None, target=None, label="Compared with"):
        """
        Create an existing manual relationship for update and permission tests

        Parameters
        ----------
        collection : ResearchCollection or None, optional
            Owning collection.
        source, target : JSONData or None, optional
            Endpoint fixtures.
        label : str, optional
            Explicit manual label.

        Returns
        -------
        CollectionRelationship
            Persisted relationship fixture.
        """
        return CollectionRelationship.objects.create(
            collection=collection or self.collection, source=source or self.source,
            target=target or self.target, label=label,
        )

    def delete(self, relationship, revision=None):
        """
        Submit a version checked deletion to the actual endpoint

        Parameters
        ----------
        relationship : CollectionRelationship
            Relationship whose deletion is requested.
        revision : object or None, optional
            Posted revision, defaulting to the fixture's current revision.

        Returns
        -------
        HttpResponse
            Actual deletion response.
        """
        return self.client.post(
            reverse("collection_relationship_delete", args=[relationship.collection_id, relationship.pk]),
            {"revision": relationship.revision if revision is None else revision}, HTTP_ACCEPT="application/json",
        )

    def test_save_keeps_an_explicit_directed_relationship(self):
        """
        Create a persisted user link without rewriting either original object
        """
        original_source = self.source.data.copy()
        original_target = self.target.data.copy()
        response = self.save(label="  Compared with  ")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        relationship = CollectionRelationship.objects.get()
        self.assertEqual((relationship.source_id, relationship.target_id, relationship.label),
                         (self.source.pk, self.target.pk, "Compared with"))
        self.assertEqual(relationship.revision, 1)
        self.assertEqual(response.json()["relationship"]["id"], relationship.pk)
        self.assertIn(f"edge={relationship.pk}", response.json()["redirect_url"])
        self.source.refresh_from_db()
        self.target.refresh_from_db()
        self.assertEqual(self.source.data, original_source)
        self.assertEqual(self.target.data, original_target)
        self.assertEqual(self.source.access_type, "c")

    def test_public_and_shared_members_can_be_linked(self):
        """
        Allow explicit links to accessible records without requiring record ownership
        """
        response = self.save(source=self.public.pk, target=self.shared.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CollectionRelationship.objects.get().source_id, self.public.pk)
        self.assertEqual(CollectionRelationship.objects.get().target_id, self.shared.pk)

    def test_invalid_and_repeated_fields_never_create_a_partial_link(self):
        """
        Reject ambiguous form values, invalid IDs and unusable names
        """
        cases = [
            {"source": "0"}, {"source": "-1"}, {"source": "1.0"}, {"source": " 1"},
            {"source": "+1"}, {"source": "١"}, {"source": "9223372036854775808"},
            {"source": [self.source.pk, self.target.pk]}, {"target": [self.target.pk, self.target.pk]},
            {"label": ""}, {"label": " \t "}, {"label": "x" * 121}, {"label": "first\nsecond"},
            {"label": ["Compared with", "Another label"]}, {"source": self.target.pk},
            {"relationship_id": "1"}, {"revision": "1"}, {"relationship_id": ["", ""]},
            {"revision": ["", ""]}, {"relationship_id": "x", "revision": "x"},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                response = self.save(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertFalse(CollectionRelationship.objects.exists())

    def test_query_parameters_cannot_compete_with_posted_fields(self):
        """
        Reject a second source of meaningful mutation parameters
        """
        response = self.client.post(
            reverse("collection_relationship_save", args=[self.collection.pk]) + f"?source={self.target.pk}",
            {"source": self.source.pk, "target": self.target.pk, "label": "Compared with"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CollectionRelationship.objects.exists())

    def test_missing_hidden_and_nonmember_endpoints_fail_without_disclosure(self):
        """
        Require both endpoint records to be accessible members of this collection
        """
        self.collection.members.add(self.hidden)
        for object_id in (self.hidden.pk, self.outside.pk, 999999):
            with self.subTest(object_id=object_id):
                response = self.save(target=object_id)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("Secret simulation", response.content.decode())
                self.assertNotIn("secret-identifier", response.content.decode())
                self.assertFalse(CollectionRelationship.objects.exists())

    def test_duplicate_links_are_rejected_but_direction_and_explicit_names_remain_distinct(self):
        """
        Reject accidental duplication while preserving supplied directional meaning
        """
        relationship = self.link()
        self.assertEqual(self.save().status_code, 400)
        self.assertEqual(self.save(label="  Compared with  ").status_code, 400)
        self.assertEqual(CollectionRelationship.objects.count(), 1)
        self.assertEqual(self.save(source=self.target.pk, target=self.source.pk).status_code, 200)
        self.assertEqual(self.save(label="Derived from").status_code, 200)
        relationship.refresh_from_db()
        self.assertEqual(relationship.revision, 1)

    def test_update_replaces_endpoints_and_label_and_increments_revision(self):
        """
        Change the same saved connection after rechecking both new endpoints
        """
        relationship = self.link()
        response = self.save(relationship_id=relationship.pk, revision=1, target=self.public.pk, label="Uses reference")
        self.assertEqual(response.status_code, 200)
        relationship.refresh_from_db()
        self.assertEqual((relationship.target_id, relationship.label, relationship.revision),
                         (self.public.pk, "Uses reference", 2))
        self.assertEqual(CollectionRelationship.objects.count(), 1)

    def test_stale_update_and_delete_preserve_the_current_saved_connection(self):
        """
        Prevent an older tab from replacing or removing a newer revision
        """
        relationship = self.link()
        self.assertEqual(self.save(relationship_id=relationship.pk, revision=1, label="Newer label").status_code, 200)
        response = self.save(relationship_id=relationship.pk, revision=1, label="Stale label")
        self.assertEqual(response.status_code, 409)
        self.assertIn("another tab", response.json()["error"])
        self.assertEqual(self.delete(relationship, revision=1).status_code, 409)
        relationship.refresh_from_db()
        self.assertEqual((relationship.label, relationship.revision), ("Newer label", 2))

    def test_update_cannot_replace_an_inaccessible_old_endpoint(self):
        """
        Hide and protect a saved link after its previous target becomes private
        """
        relationship = self.link(target=self.public)
        JSONData.objects.filter(pk=self.public.pk).update(access_type="c")
        response = self.save(relationship_id=relationship.pk, revision=1, target=self.target.pk)
        self.assertEqual(response.status_code, 400)
        relationship.refresh_from_db()
        self.assertEqual(relationship.target_id, self.public.pk)
        self.assertEqual(self.delete(relationship).status_code, 400)

    def test_update_to_a_duplicate_or_nonmember_leaves_original_unchanged(self):
        """
        Reject the full edit when its replacement conflicts or loses membership
        """
        first = self.link()
        other = self.link(label="Derived from")
        response = self.save(relationship_id=first.pk, revision=1, label=other.label)
        self.assertEqual(response.status_code, 400)
        response = self.save(relationship_id=first.pk, revision=1, target=self.outside.pk)
        self.assertEqual(response.status_code, 400)
        first.refresh_from_db()
        self.assertEqual((first.target_id, first.label, first.revision), (self.target.pk, "Compared with", 1))

    def test_relationship_identity_cannot_cross_collections(self):
        """
        Reject foreign saved identities even when submitted endpoints are accessible
        """
        foreign = self.link(collection=self.foreign_collection, source=self.public, target=self.hidden)
        response = self.save(relationship_id=foreign.pk, revision=1)
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("collection_relationship_delete", args=[self.collection.pk, foreign.pk]),
            {"revision": 1}, HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(CollectionRelationship.objects.filter(pk=foreign.pk).exists())

    def test_delete_requires_one_current_revision_and_retains_original_data(self):
        """
        Delete only the manual edge and reject malformed deletion versions
        """
        relationship = self.link()
        for revision in ("", "0", " 1", "1.0", ["1", "1"]):
            with self.subTest(revision=revision):
                self.assertEqual(self.delete(relationship, revision=revision).status_code, 400)
                self.assertTrue(CollectionRelationship.objects.filter(pk=relationship.pk).exists())
        self.assertEqual(self.delete(relationship).status_code, 200)
        self.assertFalse(CollectionRelationship.objects.filter(pk=relationship.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=self.source.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=self.target.pk).exists())
        self.assertEqual(self.collection.members.count(), 4)

    def test_only_the_owner_can_read_or_modify_saved_relationships(self):
        """
        Keep relationship endpoints and exports private to their collection owner
        """
        relationship = self.link()
        urls = [
            reverse("collection_relationship_save", args=[self.collection.pk]),
            reverse("collection_relationship_delete", args=[self.collection.pk, relationship.pk]),
            reverse("collection_relationship_export", args=[self.collection.pk]),
        ]
        self.client.force_login(self.other)
        for url in urls:
            method = self.client.get if url.endswith("export/") else self.client.post
            response = method(url, {"revision": 1}, HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(self.collection.title, response.content.decode())
        self.assertFalse(accessible_relationships(self.other, self.collection).exists())
        self.assertTrue(CollectionRelationship.objects.filter(pk=relationship.pk).exists())

    def test_login_methods_and_csrf_protect_mutation_routes(self):
        """
        Retain standard authentication, POST and CSRF requirements
        """
        relationship = self.link()
        save_url = reverse("collection_relationship_save", args=[self.collection.pk])
        delete_url = reverse("collection_relationship_delete", args=[self.collection.pk, relationship.pk])
        export_url = reverse("collection_relationship_export", args=[self.collection.pk])
        for url in (save_url, delete_url):
            self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(export_url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(save_url, {"source": self.source.pk, "target": self.target.pk, "label": "Unsafe"}).status_code, 403)
        self.assertEqual(csrf_client.post(delete_url, {"revision": 1}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(save_url).status_code, 302)
        self.assertEqual(self.client.get(export_url).status_code, 302)
        self.assertEqual(CollectionRelationship.objects.count(), 1)

    def test_visible_links_require_current_access_and_membership_at_both_ends(self):
        """
        Exclude whole links when either endpoint becomes unavailable
        """
        visible = self.link()
        public = self.link(target=self.public)
        shared = self.link(source=self.shared)
        self.link(target=self.outside)
        self.link(target=self.hidden)
        self.assertEqual(set(accessible_relationships(self.owner, self.collection).values_list("pk", flat=True)),
                         {visible.pk, public.pk, shared.pk})
        self.shared.shared_users.remove(self.owner)
        JSONData.objects.filter(pk=self.public.pk).update(access_type="c")
        self.assertEqual(list(accessible_relationships(self.owner, self.collection)), [visible])
        self.collection.members.remove(self.source)
        self.assertFalse(accessible_relationships(self.owner, self.collection).exists())
        self.assertEqual(CollectionRelationship.objects.count(), 5)

    def test_collection_limit_rejects_creation_but_allows_existing_edits(self):
        """
        Bound stored connections while keeping a full collection editable
        """
        CollectionRelationship.objects.bulk_create([
            CollectionRelationship(collection=self.collection, source=self.source, target=self.target, label=f"Manual {number}")
            for number in range(MAX_COLLECTION_RELATIONSHIPS)
        ])
        response = self.save()
        self.assertEqual(response.status_code, 400)
        self.assertIn("limit", response.json()["error"])
        first = CollectionRelationship.objects.first()
        self.assertEqual(self.save(relationship_id=first.pk, revision=1, label="Revised label").status_code, 200)
        self.assertEqual(CollectionRelationship.objects.count(), MAX_COLLECTION_RELATIONSHIPS)

    def test_save_failure_rolls_back_the_relationship(self):
        """
        Keep a failed collection update from committing a new connection alone
        """
        with patch.object(ResearchCollection, "save", side_effect=RuntimeError("Simulated database failure")):
            with self.assertRaisesRegex(RuntimeError, "Simulated database failure"):
                self.save()
        self.assertFalse(CollectionRelationship.objects.exists())

    def test_member_removal_cleans_only_incident_links(self):
        """
        Remove manual references alongside memberships without deleting records
        """
        incident = self.link()
        retained = self.link(source=self.public, target=self.shared)
        response = self.client.post(reverse("collection_remove", args=[self.collection.pk]), {"selected_objects": [self.source.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CollectionRelationship.objects.filter(pk=incident.pk).exists())
        self.assertTrue(CollectionRelationship.objects.filter(pk=retained.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=self.source.pk).exists())

    def test_explicit_cleanup_removes_hidden_links_without_disclosing_them(self):
        """
        Clear saved manual connections when unavailable member references are cleared
        """
        visible = self.link()
        hidden = self.link(target=self.public, label="Private manual annotation")
        JSONData.objects.filter(pk=self.public.pk).update(access_type="c")
        response = self.client.post(reverse("collection_cleanup", args=[self.collection.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CollectionRelationship.objects.filter(pk=visible.pk).exists())
        self.assertFalse(CollectionRelationship.objects.filter(pk=hidden.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=self.public.pk).exists())

    def test_object_and_collection_deletion_cascade_only_their_manual_links(self):
        """
        Avoid orphan relations while preserving unrelated collections and records
        """
        removed = self.link()
        retained = self.link(source=self.public, target=self.shared)
        self.source.delete()
        self.assertFalse(CollectionRelationship.objects.filter(pk=removed.pk).exists())
        self.assertTrue(CollectionRelationship.objects.filter(pk=retained.pk).exists())
        self.collection.delete()
        self.assertFalse(CollectionRelationship.objects.exists())
        self.assertTrue(JSONData.objects.filter(pk=self.target.pk).exists())

    def test_database_constraints_reject_self_links_and_exact_duplicates(self):
        """
        Retain essential relationship integrity even outside the HTTP mutation path
        """
        self.link()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(target=self.source)

    def test_relationship_export_is_versioned_private_and_access_filtered(self):
        """
        Export explicit links and supplied identifiers without hidden endpoint metadata
        """
        relationship = self.link(label="User provided comparison")
        self.link(target=self.public, label="Soon unavailable link")
        self.link(target=self.outside, label="Outside membership link")
        JSONData.objects.filter(pk=self.public.pk).update(access_type="c")
        response = self.client.get(reverse("collection_relationship_export", args=[self.collection.pk]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["format"], "research-collection-relationships")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["relationships"], [{
            "id": relationship.pk, "source": {"id": self.source.pk, "identifier": "source-original", "title": "Source simulation"},
            "target": {"id": self.target.pk, "identifier": "target-original", "title": "Target simulation"},
            "label": "User provided comparison", "origin": "user", "revision": 1,
        }])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertNotIn("Soon unavailable", response.content.decode())
        self.assertNotIn("Outside membership", response.content.decode())

    def test_original_json_export_is_unchanged_after_relationship_creation(self):
        """
        Keep user annotations out of the collection's original record download
        """
        self.assertEqual(self.save(label="Only in collection graph").status_code, 200)
        response = self.client.get(reverse("collection_export", args=[self.collection.pk]))
        payload = json.loads(b"".join(response.streaming_content))
        self.assertIn(self.source.data, payload)
        self.assertIn(self.target.data, payload)
        self.assertNotIn("Only in collection graph", json.dumps(payload))

    def test_native_forms_save_and_delete_with_ordinary_redirects(self):
        """
        Keep complete relationship editing available without JavaScript
        """
        response = self.client.post(reverse("collection_relationship_save", args=[self.collection.pk]), {
            "source": self.source.pk, "target": self.target.pk, "label": "Native connection",
        })
        self.assertEqual(response.status_code, 302)
        relationship = CollectionRelationship.objects.get()
        self.assertIn(f"edge={relationship.pk}", response.url)
        response = self.client.post(
            reverse("collection_relationship_delete", args=[self.collection.pk, relationship.pk]),
            {"revision": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CollectionRelationship.objects.exists())

    def test_native_validation_keeps_submitted_values_escaped(self):
        """
        Return the usable bound form with escaped names after rejecting a self link
        """
        response = self.client.post(reverse("collection_relationship_save", args=[self.collection.pk]), {
            "source": self.source.pk, "target": self.source.pk, "label": '<script>alert("x")</script>',
        })
        self.assertEqual(response.status_code, 400)
        form = response.context["manual_editor"]["form"]
        self.assertEqual(form["source"].value(), str(self.source.pk))
        self.assertEqual(form["target"].value(), str(self.source.pk))
        self.assertEqual(form["label"].value(), '<script>alert("x")</script>')
        self.assertContains(response, "Choose a different data object", status_code=400)
        self.assertNotContains(response, '<script>alert("x")</script>', status_code=400)
        self.assertFalse(CollectionRelationship.objects.exists())

    def test_native_stale_edit_retains_identity_and_posted_revision(self):
        """
        Preserve the attempted edit while exposing a safe link to reload its saved version
        """
        relationship = self.link()
        self.assertEqual(self.save(relationship_id=relationship.pk, revision=1, label="Current label").status_code, 200)
        response = self.client.post(reverse("collection_relationship_save", args=[self.collection.pk]), {
            "source": self.source.pk, "target": self.target.pk, "label": "Older draft",
            "relationship_id": relationship.pk, "revision": 1,
        })
        self.assertEqual(response.status_code, 409)
        editor = response.context["manual_editor"]
        self.assertEqual(editor["selected"]["id"], relationship.pk)
        self.assertEqual(editor["form"]["label"].value(), "Older draft")
        self.assertEqual(editor["form"]["revision"].value(), "1")
        self.assertIn(f"edge={relationship.pk}", editor["reload_url"])
        relationship.refresh_from_db()
        self.assertEqual(relationship.label, "Current label")

    def test_native_stale_delete_returns_the_authorized_relationship_form(self):
        """
        Keep deletion conflicts understandable without exposing unavailable endpoints
        """
        relationship = self.link()
        self.assertEqual(self.save(relationship_id=relationship.pk, revision=1, label="Current label").status_code, 200)
        response = self.client.post(
            reverse("collection_relationship_delete", args=[self.collection.pk, relationship.pk]), {"revision": 1},
        )
        self.assertEqual(response.status_code, 409)
        editor = response.context["manual_editor"]
        self.assertEqual(editor["selected"]["id"], relationship.pk)
        self.assertEqual(editor["form"]["label"].value(), "Current label")
        self.assertEqual(editor["form"]["revision"].value(), 1)
        self.assertTrue(CollectionRelationship.objects.filter(pk=relationship.pk).exists())


@skipUnlessDBFeature("has_select_for_update")
class CollectionRelationshipConcurrencyTests(TransactionTestCase):
    """
    Exercise actual overlapping graph mutations on independent database connections
    """

    def setUp(self):
        """
        Prepare a collection whose endpoints are committed before worker requests start
        """
        self.owner = User.objects.create_user(username="relationship-race-owner")
        self.source = JSONData.objects.create(owner=self.owner, data={"title": "Race source"})
        self.target = JSONData.objects.create(owner=self.owner, data={"title": "Race target"})
        self.collection = ResearchCollection.objects.create(owner=self.owner, title="Concurrent relationships")
        self.collection.members.add(self.source, self.target)

    def simultaneous(self, actions):
        """
        Bring two independent requests to the collection lock together

        Parameters
        ----------
        actions : list of tuple
            A mutation name and its form fields for each worker.

        Returns
        -------
        list of int
            Completed response status codes in worker order.
        """
        ready = Barrier(2)
        owned_collection = collection_views._owned_collection

        def synchronize(request, pk, *, lock=False):
            """
            Align only the entry to each real transaction lock

            Parameters
            ----------
            request : HttpRequest
                Worker request with its own database connection.
            pk : int
                Collection being modified.
            lock : bool, optional
                Whether this lookup obtains the transaction lock.

            Returns
            -------
            ResearchCollection
                Collection returned by the unchanged database operation.
            """
            if lock:
                ready.wait(timeout=10)
            return owned_collection(request, pk, lock=lock)

        def submit(action):
            """
            Run one complete authenticated mutation and close its connection

            Parameters
            ----------
            action : tuple
                Mutation name and posted fields.

            Returns
            -------
            int
                Completed response status.
            """
            close_old_connections()
            try:
                name, fields = action
                request = RequestFactory().post("/graph/", fields, HTTP_ACCEPT="application/json")
                request.user = self.owner
                request.session = {}
                request._messages = FallbackStorage(request)
                view = relationship_views.collection_relationship_save if name == "save" else collection_views.collection_remove
                return view(request, self.collection.pk).status_code
            finally:
                connections.close_all()

        with patch.object(relationship_views, "_owned_collection", side_effect=synchronize), \
                patch.object(collection_views, "_owned_collection", side_effect=synchronize), \
                ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_simultaneous_duplicate_creates_commit_exactly_one_relationship(self):
        """
        Serialize identical creations without database errors or duplicate links
        """
        fields = {"source": self.source.pk, "target": self.target.pk, "label": "Compared with"}
        statuses = self.simultaneous([("save", fields), ("save", fields)])
        self.assertEqual(sorted(statuses), [200, 400])
        self.assertEqual(CollectionRelationship.objects.count(), 1)

    def test_simultaneous_stale_edits_have_one_success_and_one_conflict(self):
        """
        Preserve the winning edit when two tabs submit the same previous revision
        """
        relationship = CollectionRelationship.objects.create(
            collection=self.collection, source=self.source, target=self.target, label="Original label",
        )
        fields = {"source": self.source.pk, "target": self.target.pk, "relationship_id": relationship.pk, "revision": 1}
        statuses = self.simultaneous([
            ("save", {**fields, "label": "First edit"}), ("save", {**fields, "label": "Second edit"}),
        ])
        self.assertEqual(sorted(statuses), [200, 409])
        relationship.refresh_from_db()
        self.assertEqual(relationship.revision, 2)
        self.assertEqual(relationship.label, "First edit" if statuses[0] == 200 else "Second edit")

    def test_member_removal_and_relationship_creation_cannot_leave_an_orphan(self):
        """
        Serialize reference removal and creation so the final collection stays consistent
        """
        statuses = self.simultaneous([
            ("save", {"source": self.source.pk, "target": self.target.pk, "label": "Compared with"}),
            ("remove", {"selected_objects": [self.target.pk]}),
        ])
        self.assertIn(statuses[0], (200, 400))
        self.assertEqual(statuses[1], 302)
        self.assertFalse(self.collection.members.filter(pk=self.target.pk).exists())
        self.assertFalse(CollectionRelationship.objects.exists())
        self.assertTrue(JSONData.objects.filter(pk=self.target.pk).exists())
