"""
Verify private saved analysis state, source checks and explicit revisions.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from urllib.parse import parse_qs, urlsplit
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import signing
from django.db import close_old_connections, connection, connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .collection_navigation import CONTEXT_SALT
from .models import CollectionRelationship, JSONData, ResearchCollection, SavedStudyAnalysis
from .study_analyses import (
    AnalysisForm, analysis_parameters, build_analysis_context,
    collection_analysis_save, collection_analysis_delete,
)


class SavedAnalysisTests(TestCase):
    """
    Exercise stored choices without retaining or changing source JSON.
    """

    def setUp(self):
        """
        Create an owned collection with one explicitly shared source.
        """
        self.owner = User.objects.create_user(username="analysis-owner")
        self.other = User.objects.create_user(username="analysis-other")
        self.first = JSONData.objects.create(owner=self.owner, data={"title": "Reference", "value": 1})
        self.second = JSONData.objects.create(owner=self.other, data={"title": "Shared source", "value": 2})
        self.second.shared_users.add(self.owner)
        self.collection = ResearchCollection.objects.create(owner=self.owner, title="Material study")
        self.collection.members.add(self.first, self.second)
        self.state = {"panel": "compare", "compare": f"{self.second.pk},{self.first.pk}", "links": "members",
                      "inspect": "1", "detail_status": "different", "detail_q": "C11",
                      "curve_component": "11", "curve_strain": "plastic", "curve_view": "overlay", "curve_open": "1"}
        self.client.force_login(self.owner)

    def request(self, fields, *, user=None, collection=None):
        """
        Build a signed JSON mutation request for the chosen owner and collection.

        Parameters
        ----------
        fields : dict
            Submitted values overriding the normal analysis form.
        user : User or None, optional
            Acting user, defaulting to the collection owner.
        collection : ResearchCollection or None, optional
            Signed scope, defaulting to the fixture collection.

        Returns
        -------
        HttpRequest
            Authenticated request with ordinary message storage.
        """
        actor = user or self.owner
        scope = collection or self.collection
        token = signing.dumps({"user": actor.pk, "kind": "collection", "target": scope.pk,
                               "params": {"links": "members"}}, salt=CONTEXT_SALT)
        data = {"graph_context": token, "workspace_state": json.dumps(self.state),
                "title": "Temperature comparison", "notes": "Compare these recorded settings.", "intent": "create"}
        data.update(fields)
        request = RequestFactory().post("/graph/analyses/save/", data, HTTP_ACCEPT="application/json")
        request.user = actor
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def save(self, fields=None):
        """
        Save one valid analysis and return its stored row.

        Parameters
        ----------
        fields : dict or None, optional
            Form values replacing the normal fixture choices.

        Returns
        -------
        SavedStudyAnalysis
            Confirmed newly stored analysis.
        """
        response = collection_analysis_save(self.request(fields or {}), self.collection.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)["ok"])
        return SavedStudyAnalysis.objects.latest("pk")

    def context(self, analysis, state=None):
        """
        Build an active analysis context with a complete current selection.

        Parameters
        ----------
        analysis : SavedStudyAnalysis
            Analysis to show in the workspace.
        state : dict or None, optional
            Current controls, defaulting to the saved state.

        Returns
        -------
        dict
            Presentation context after current access checks.
        """
        params = {**(state or self.state), "analysis": str(analysis.pk)}
        request = RequestFactory().get("/graph/", params)
        request.user = self.owner
        return build_analysis_context(request, {"study_return_params": params}, request.GET, collection=self.collection)

    def test_save_retains_order_and_exact_choices_without_copying_source_data(self):
        """
        Store ordered reference choices and notes without raw records.
        """
        before = list(JSONData.objects.values_list("pk", "data"))
        item = self.save({"title": "  Temperature comparison  "})
        self.assertEqual(item.title, "Temperature comparison")
        self.assertEqual(item.state, self.state)
        self.assertEqual(set(item.source_digests), {str(self.first.pk), str(self.second.pk)})
        self.assertTrue(all(len(value) == 32 for value in item.source_digests.values()))
        self.assertEqual(list(JSONData.objects.values_list("pk", "data")), before)
        self.assertEqual(item.revision, 1)

    def test_open_restores_full_selection_and_controls(self):
        """
        Reopening produces a current collection URL with every stored control.
        """
        item = self.save()
        response = self.client.get(reverse("collection_analysis_open", args=[self.collection.pk, item.pk]))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.url).query)
        for key, value in self.state.items():
            self.assertEqual(query[key], [value])
        self.assertEqual(query["analysis"], [str(item.pk)])
        item.refresh_from_db()
        self.assertEqual(item.revision, 1)

    def test_active_context_detects_raw_change_without_accepting_new_baseline(self):
        """
        Show source changes even when cached scalar summaries are unchanged.
        """
        item = self.save()
        initial = deepcopy(item.source_digests)
        self.assertFalse(self.context(item)["active"]["changed"])
        JSONData.objects.filter(pk=self.first.pk).update(data={"title": "Reference", "value": 99})
        context = self.context(item)
        self.assertTrue(context["active"]["changed"])
        self.assertFalse(context["active"]["unavailable"])
        item.refresh_from_db()
        self.assertEqual(item.source_digests, initial)

    def test_active_context_marks_changed_view_and_preserves_explicit_clear(self):
        """
        Distinguish current controls without merging saved values back in.
        """
        item = self.save()
        state = {"links": "members", "panel": "compare", "compare": self.state["compare"]}
        context = self.context(item, state)
        self.assertTrue(context["active"]["dirty"])
        self.assertNotIn("detail_q", json.loads(context["state_json"]))

    def test_revoke_and_remove_block_whole_open_without_hidden_source_metadata(self):
        """
        Retain the analysis while refusing a partially accessible comparison.
        """
        item = self.save()
        self.second.shared_users.clear()
        context = self.context(item)
        self.assertTrue(context["active"]["unavailable"])
        self.assertEqual(context["active_state_json"], "{}")
        response = self.client.get(reverse("collection_analysis_open", args=[self.collection.pk, item.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "Shared source", status_code=400)
        self.assertEqual(SavedStudyAnalysis.objects.count(), 1)
        self.second.shared_users.add(self.owner)
        self.collection.members.remove(self.second)
        self.assertTrue(self.context(item)["active"]["unavailable"])

    def test_update_requires_revision_and_save_as_new_keeps_original(self):
        """
        Apply explicit edits once and keep copying separate from updating.
        """
        item = self.save()
        update = {"intent": "update", "analysis_id": item.pk, "revision": 1, "notes": "Revised observation"}
        response = collection_analysis_save(self.request(update), self.collection.pk)
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.revision, 2)
        self.assertEqual(item.notes, "Revised observation")
        response = collection_analysis_save(self.request({**update, "notes": "Stale observation"}), self.collection.pk)
        self.assertEqual(response.status_code, 409)
        item.refresh_from_db()
        self.assertEqual(item.notes, "Revised observation")
        copied = self.save({**update, "intent": "create", "title": "Copy"})
        self.assertNotEqual(copied.pk, item.pk)
        self.assertEqual(copied.revision, 1)

    def test_delete_uses_revision_and_does_not_remove_objects_or_collection(self):
        """
        Delete only the requested analysis after checking its revision.
        """
        item = self.save()
        response = collection_analysis_delete(self.request({"revision": 2}), self.collection.pk, item.pk)
        self.assertEqual(response.status_code, 409)
        response = collection_analysis_delete(self.request({"revision": 1}), self.collection.pk, item.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SavedStudyAnalysis.objects.filter(pk=item.pk).exists())
        self.assertEqual(JSONData.objects.count(), 2)
        self.assertTrue(ResearchCollection.objects.filter(pk=self.collection.pk).exists())

    def test_rejects_hidden_nonmember_duplicate_or_partial_selection(self):
        """
        Never silently drop an invalid record from a saved selection.
        """
        outside = JSONData.objects.create(owner=self.owner, data={"title": "Outside"})
        for ids in (str(self.first.pk), f"{self.first.pk},{self.first.pk}", f"{self.first.pk},{outside.pk}"):
            with self.subTest(ids=ids):
                state = {**self.state, "compare": ids}
                response = collection_analysis_save(self.request({"workspace_state": json.dumps(state)}), self.collection.pk)
                self.assertEqual(response.status_code, 400)
        self.second.shared_users.clear()
        self.assertEqual(collection_analysis_save(self.request({}), self.collection.pk).status_code, 400)
        self.assertEqual(SavedStudyAnalysis.objects.count(), 0)

    def test_rejects_unsigned_wrong_scope_and_wrong_owner(self):
        """
        Require signed navigation for this private collection.
        """
        other_collection = ResearchCollection.objects.create(owner=self.owner, title="Other")
        response = collection_analysis_save(self.request({"graph_context": ""}), self.collection.pk)
        self.assertEqual(response.status_code, 400)
        response = collection_analysis_save(self.request({}, collection=other_collection), self.collection.pk)
        self.assertEqual(response.status_code, 400)
        self.client.force_login(self.other)
        response = self.client.get(reverse("collection_analysis_open", args=[self.collection.pk, 1]))
        self.assertEqual(response.status_code, 404)

    def test_rejects_malformed_unknown_repeated_and_oversized_state(self):
        """
        Keep stored state flat, bounded and restricted to canonical controls.
        """
        states = ('[]', '{"compare":"1,2","compare":"2,1"}', '{"return_url":"https://example.com"}',
                  json.dumps({**self.state, "analysis": "1"}), '{"compare":' + '[' * 1000,
                  json.dumps({**self.state, "detail_q": "x" * 17000}))
        for state in states:
            with self.subTest(state=state[:80]):
                response = collection_analysis_save(self.request({"workspace_state": state}), self.collection.pk)
                self.assertEqual(response.status_code, 400)
        request = self.request({})
        request.POST._mutable = True
        request.POST.appendlist("title", "Second title")
        self.assertEqual(collection_analysis_save(request, self.collection.pk).status_code, 400)

    def test_title_notes_limits_and_single_line_names(self):
        """
        Validate user text without silently truncating it.
        """
        for fields in ({"title": " "}, {"title": "x" * 121}, {"title": "line\nbreak"}, {"notes": "x" * 5001}):
            response = collection_analysis_save(self.request(fields), self.collection.pk)
            self.assertEqual(response.status_code, 400)
        item = self.save({"title": "x" * 120, "notes": "Line one\nLine two"})
        self.assertEqual(item.notes, "Line one\nLine two")

    def test_analysis_limit_and_list_pagination(self):
        """
        Bound stored analyses and list rows within one private collection.
        """
        SavedStudyAnalysis.objects.bulk_create([
            SavedStudyAnalysis(collection=self.collection, title=f"Analysis {index}", state=self.state)
            for index in range(100)
        ])
        self.assertEqual(collection_analysis_save(self.request({}), self.collection.pk).status_code, 400)
        request = RequestFactory().get("/graph/", {"analyses_page": "2"})
        request.user = self.owner
        context = build_analysis_context(request, {"study_return_params": self.state}, request.GET, collection=self.collection)
        self.assertEqual(len(context["rows"]), 12)
        self.assertEqual(context["page"].number, 2)
        self.assertEqual(context["page"].paginator.count, 100)

    def test_native_csrf_and_post_requirements(self):
        """
        Keep mutation endpoints protected with ordinary Django middleware.
        """
        url = reverse("collection_analysis_save", args=[self.collection.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        self.assertEqual(strict.post(url, {"title": "No CSRF"}).status_code, 403)

    def test_analysis_control_validation(self):
        """
        Reject malformed identities and pages before signing navigation.
        """
        self.assertEqual(analysis_parameters({"analysis": "2", "analyses_page": "1"}), {"analysis": "2"})
        for params in ({"analysis": "0"}, {"analysis": "-1"}, {"analyses_page": "0"}, {"analysis": "1.0"}):
            with self.assertRaises(ValueError):
                analysis_parameters(params)

    def test_form_retains_submitted_text_on_invalid_state(self):
        """
        Invalid state cannot discard the user's analysis notes.
        """
        form = AnalysisForm({"title": "Keep me", "notes": "My unfinished observation", "workspace_state": "[]", "intent": "create"})
        self.assertFalse(form.is_valid())
        self.assertEqual(form["notes"].value(), "My unfinished observation")

    def test_actual_byte_limit_precedes_digest_and_keeps_existing_analysis_manageable(self):
        """
        Stop expensive source hashing while retaining own notes and deletion.
        """
        item = self.save()
        with patch("apps.pages.study_analyses.MAX_SOURCE_BYTES", 5):
            with CaptureQueriesContext(connection) as queries:
                response = collection_analysis_save(self.request({}), self.collection.pk)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(any("MD5(" in query["sql"].upper() for query in queries))
            context = self.context(item)
            self.assertTrue(context["active"]["unavailable"])
            self.assertEqual(context["active"]["notes"], item.notes)
            response = self.client.get(reverse("collection_analysis_open", args=[self.collection.pk, item.pk]))
            self.assertEqual(response.status_code, 400)
            response = collection_analysis_delete(self.request({"revision": 1}), self.collection.pk, item.pk)
            self.assertEqual(response.status_code, 200)

    def test_native_stale_save_preserves_entered_notes_and_revision(self):
        """
        Return a visible native form conflict without replacing submitted text.
        """
        item = self.save()
        item.revision = 2
        item.save(update_fields=["revision"])
        request = self.request({"intent": "update", "analysis_id": item.pk, "revision": 1, "notes": "Unsaved native observation"})
        request.META["HTTP_ACCEPT"] = "text/html"
        response = collection_analysis_save(request, self.collection.pk)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Unsaved native observation", status_code=409)
        self.assertContains(response, 'name="revision" value="1"', status_code=409)

    def test_native_delete_conflict_does_not_render_saved_hidden_ids(self):
        """
        Deleted or revoked sources never reappear in a failed delete form.
        """
        item = self.save()
        hidden_ids = self.state["compare"]
        self.second.shared_users.clear()
        request = self.request({"revision": 99})
        request.META["HTTP_ACCEPT"] = "text/html"
        response = collection_analysis_delete(request, self.collection.pk, item.pk)
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, hidden_ids, status_code=409)
        self.assertNotContains(response, "Shared source", status_code=409)

    def test_native_nested_invalid_state_preserves_notes_without_reparsing_raw_json(self):
        """
        An excessively nested native form returns validation feedback, not an error.
        """
        item = self.save()
        sources = list(JSONData.objects.values_list("pk", "data"))
        saved_state = deepcopy(item.state)
        nested = "[" * 1500 + "0" + "]" * 1500
        request = self.request({"workspace_state": nested, "notes": "Keep my pending observation",
                                "intent": "update", "analysis_id": item.pk, "revision": item.revision})
        request.META["HTTP_ACCEPT"] = "text/html"
        response = collection_analysis_save(request, self.collection.pk)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Keep my pending observation", status_code=400)
        self.assertEqual(SavedStudyAnalysis.objects.count(), 1)
        item.refresh_from_db()
        self.assertEqual(item.revision, 1)
        self.assertEqual(item.state, saved_state)
        self.assertEqual(item.notes, "Compare these recorded settings.")
        self.assertEqual(list(JSONData.objects.values_list("pk", "data")), sources)

    def test_saved_state_retains_the_canonical_manual_relationship_page(self):
        """
        Saving and reopening a comparison preserves its second relationship page.
        """
        CollectionRelationship.objects.bulk_create([
            CollectionRelationship(collection=self.collection, source=self.first, target=self.second,
                                   label=f"Recorded comparison {index}")
            for index in range(13)
        ])
        response = self.client.get(reverse("collection_detail", args=[self.collection.pk]),
                                   {**self.state, "relationships_page": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["manual_editor"]["page"].number, 2)
        form_state = response.context["study_analyses"]["form"]["workspace_state"].value()
        self.assertEqual(json.loads(form_state)["relationships_page"], "2")
        saved = self.client.post(reverse("collection_analysis_save", args=[self.collection.pk]), {
            "graph_context": response.context["graph_context"], "workspace_state": form_state,
            "title": "Relationship inspection", "notes": "Continue at page two", "intent": "create",
        }, HTTP_ACCEPT="application/json")
        self.assertEqual(saved.status_code, 200, saved.content)
        item = SavedStudyAnalysis.objects.latest("pk")
        self.assertEqual(item.state["relationships_page"], "2")
        opened = self.client.get(reverse("collection_analysis_open", args=[self.collection.pk, item.pk]))
        self.assertEqual(opened.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(opened.url).query)["relationships_page"], ["2"])
        restored = self.client.get(opened.url)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.context["manual_editor"]["page"].number, 2)

    def test_native_invalid_title_keeps_the_comparison_and_can_be_corrected(self):
        """
        A title error keeps valid selected records and allows the next submission.
        """
        fields = self.request({"title": "", "notes": "Keep these choices"}).POST.copy()
        url = reverse("collection_analysis_save", args=[self.collection.pk])
        response = self.client.post(url, fields)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context["study_comparison"]["ids"], [self.second.pk, self.first.pk])
        self.assertTrue(response.context["study_analyses"]["can_save"])
        self.assertEqual(response.context["study_analyses"]["form"]["notes"].value(), "Keep these choices")
        self.assertEqual(SavedStudyAnalysis.objects.count(), 0)
        fields["title"] = "Corrected native analysis"
        fields["graph_context"] = response.context["graph_context"]
        corrected = self.client.post(url, fields)
        self.assertEqual(corrected.status_code, 302)
        item = SavedStudyAnalysis.objects.get()
        self.assertEqual(item.state["compare"], self.state["compare"])
        self.assertEqual(item.notes, "Keep these choices")

    def test_native_long_notes_keep_owned_active_analysis_and_copy_action(self):
        """
        A notes error retains the saved identity, revision and both explicit actions.
        """
        item = self.save()
        fields = self.request({"intent": "update", "analysis_id": item.pk, "revision": 1,
                               "notes": "x" * 5001}).POST.copy()
        response = self.client.post(reverse("collection_analysis_save", args=[self.collection.pk]), fields)
        self.assertEqual(response.status_code, 400)
        context = response.context["study_analyses"]
        self.assertEqual(context["active"]["id"], item.pk)
        self.assertTrue(context["can_save"])
        self.assertEqual(context["form"]["revision"].value(), "1")
        self.assertEqual(context["form"]["notes"].value(), "x" * 5001)
        self.assertContains(response, 'id="study-analysis-update">Save changes', status_code=400)
        self.assertContains(response, 'id="study-analysis-copy" class="is-secondary">Save as new', status_code=400)
        item.refresh_from_db()
        self.assertEqual(item.revision, 1)
        self.assertEqual(item.notes, "Compare these recorded settings.")

    def test_native_field_error_does_not_restore_foreign_analysis_or_invalid_state(self):
        """
        Recovery checks scope and never restores selections from rejected JSON.
        """
        foreign_collection = ResearchCollection.objects.create(owner=self.other, title="PRIVATE unrelated collection")
        foreign = SavedStudyAnalysis.objects.create(collection=foreign_collection, title="SECRET foreign analysis",
                                                     state=self.state, notes="SECRET foreign notes")
        url = reverse("collection_analysis_save", args=[self.collection.pk])
        fields = self.request({"title": "", "intent": "update", "analysis_id": foreign.pk, "revision": 1}).POST.copy()
        response = self.client.post(url, fields)
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.context["study_analyses"]["active"])
        self.assertNotContains(response, "SECRET foreign", status_code=400)
        fields["workspace_state"] = "[]"
        response = self.client.post(url, fields)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.context["study_analyses"]["can_save"])
        self.assertEqual(response.context["study_comparison"]["ids"], [])

    def test_analysis_labels_have_distinct_ids_beside_collection_fields(self):
        """
        Native labels identify analysis inputs rather than the collection editor.
        """
        response = self.client.get(reverse("collection_detail", args=[self.collection.pk]), self.state)
        self.assertEqual(response.status_code, 200)
        for markup in (b'id="id_title"', b'id="study-analysis-title"', b'for="study-analysis-title"',
                       b'id="study-analysis-notes"', b'for="study-analysis-notes"'):
            self.assertEqual(response.content.count(markup), 1, markup)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks and activity observations")
class SavedAnalysisLockTests(TransactionTestCase):
    """
    Observe collection and source locks across competing real database requests.
    """

    def setUp(self):
        """
        Commit an owned collection and a source shared by another owner.
        """
        self.owner = User.objects.create_user(username="analysis-lock-owner")
        self.other = User.objects.create_user(username="analysis-lock-other")
        self.first = JSONData.objects.create(owner=self.owner, data={"title": "Owned"})
        self.second = JSONData.objects.create(owner=self.other, data={"title": "Shared"})
        self.second.shared_users.add(self.owner)
        self.collection = ResearchCollection.objects.create(owner=self.owner, title="Lock study")
        self.collection.members.add(self.first, self.second)
        self.state = {"links": "members", "panel": "compare", "compare": f"{self.first.pk},{self.second.pk}"}

    def request(self, fields, *, user=None):
        """
        Create a signed request on the caller's independent database connection.

        Parameters
        ----------
        fields : dict
            Submitted form choices.
        user : User or None, optional
            Acting user for an existing source sharing action.

        Returns
        -------
        HttpRequest
            Authenticated request with messages and JSON feedback enabled.
        """
        actor = user or self.owner
        token = signing.dumps({"user": actor.pk, "kind": "collection", "target": self.collection.pk,
                               "params": {"links": "members"}}, salt=CONTEXT_SALT)
        data = {"graph_context": token, "workspace_state": json.dumps(self.state),
                "title": "Concurrent analysis", "notes": "", "intent": "create", **fields}
        request = RequestFactory().post("/graph/", data, HTTP_ACCEPT="application/json")
        request.user = actor
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def wait_for_lock(self, pid, future):
        """
        Require a real PostgreSQL lock wait before releasing the competing writer.

        Parameters
        ----------
        pid : int
            Connection running the blocked request.
        future : Future
            Worker response used to detect an unlocked operation.
        """
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.assertFalse(future.done(), "The competing request did not wait for its collection or source lock.")
            with connection.cursor() as cursor:
                cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid])
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return
            time.sleep(0.01)
        self.fail("The competing request never reached its database lock.")

    def queued(self, callback, started, backend):
        """
        Run one operation while exposing its actual backend for lock observation.

        Parameters
        ----------
        callback : callable
            View call made using the worker connection.
        started : Event
            Signals that the worker backend identity is available.
        backend : dict
            Receives the worker's PostgreSQL process identity.

        Returns
        -------
        int
            Actual HTTP response status after the transaction finishes.
        """
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend["pid"] = cursor.fetchone()[0]
            started.set()
            return callback().status_code
        finally:
            connections.close_all()

    def test_two_creates_serialize_the_collection_limit(self):
        """
        Two final-slot creates cannot exceed the collection's saved analysis cap.
        """
        SavedStudyAnalysis.objects.bulk_create([
            SavedStudyAnalysis(collection=self.collection, title=f"Existing {index}", state=self.state)
            for index in range(99)
        ])
        started, backend = Event(), {}
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                ResearchCollection.objects.select_for_update().get(pk=self.collection.pk)
                future = executor.submit(self.queued,
                    lambda: collection_analysis_save(self.request({}), self.collection.pk), started, backend)
                self.assertTrue(started.wait(5))
                self.wait_for_lock(backend["pid"], future)
                response = collection_analysis_save(self.request({}), self.collection.pk)
                self.assertEqual(response.status_code, 200)
            self.assertEqual(future.result(timeout=10), 400)
        self.assertEqual(SavedStudyAnalysis.objects.filter(collection=self.collection).count(), 100)

    def test_stale_update_and_delete_wait_then_preserve_the_winning_revision(self):
        """
        A tab that waited on the lock must recheck the latest revision.
        """
        for action in ("update", "delete"):
            with self.subTest(action=action):
                response = collection_analysis_save(self.request({}), self.collection.pk)
                self.assertEqual(response.status_code, 200)
                item = SavedStudyAnalysis.objects.latest("pk")
                fields = {"intent": "update", "analysis_id": item.pk, "revision": 1, "notes": "Waiting tab"}
                started, backend = Event(), {}
                if action == "update":
                    callback = lambda: collection_analysis_save(self.request(fields), self.collection.pk)
                else:
                    callback = lambda: collection_analysis_delete(self.request(fields), self.collection.pk, item.pk)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    with transaction.atomic():
                        ResearchCollection.objects.select_for_update().get(pk=self.collection.pk)
                        future = executor.submit(self.queued, callback, started, backend)
                        self.assertTrue(started.wait(5))
                        self.wait_for_lock(backend["pid"], future)
                        response = collection_analysis_save(self.request({**fields, "notes": "Winning tab"}), self.collection.pk)
                        self.assertEqual(response.status_code, 200)
                    self.assertEqual(future.result(timeout=10), 409)
                item.refresh_from_db()
                self.assertEqual(item.revision, 2)
                self.assertEqual(item.notes, "Winning tab")

    def test_source_revocation_is_rechecked_after_the_writer_waits(self):
        """
        Reject an old accessibility snapshot after a prior source mutation commits.
        """
        from .views import json_data_sharing_view

        started, backend = Event(), {}
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                JSONData.objects.select_for_update().get(pk=self.second.pk)
                future = executor.submit(self.queued,
                    lambda: collection_analysis_save(self.request({}), self.collection.pk), started, backend)
                self.assertTrue(started.wait(5))
                self.wait_for_lock(backend["pid"], future)
                response = json_data_sharing_view(self.request({"action": "remove_user", "user_id": self.owner.pk}, user=self.other), self.second.pk)
                self.assertEqual(response.status_code, 302)
            self.assertEqual(future.result(timeout=10), 400)
        self.assertFalse(SavedStudyAnalysis.objects.exists())
