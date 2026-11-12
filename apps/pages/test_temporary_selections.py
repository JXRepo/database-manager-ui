"""
Exercise temporary membership independently of overlapping browser session writes
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.db import close_old_connections, connections
from django.http import Http404
from django.test import RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from . import research_collections as views
from .models import JSONData, ResearchCollection, TemporaryGraphSelection


class TemporarySelectionFixture:
    """
    Retain both additions when requests started from the same session snapshot
    """

    def setUp(self):
        """
        Create a signed continuation for three independently accessible records
        """
        self.owner = User.objects.create_user(username="temporary-snapshot-owner")
        self.records = [JSONData.objects.create(owner=self.owner, data={"title": f"Run {index}"})
                        for index in range(3)]
        self.client.force_login(self.owner)
        created = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [self.records[0].pk],
        })
        workspace = self.client.get(created.url)
        self.token = workspace.context["selection_token"]
        self.context_token = workspace.context["graph_context"]
        self.session_key = self.client.session.session_key

    def request(self, record):
        """
        Load a request session before either pending request updates membership

        Parameters
        ----------
        record : JSONData
            Additional member selected in this browser tab.

        Returns
        -------
        HttpRequest
            Authenticated POST with a separately loaded session snapshot.
        """
        request = RequestFactory().post(reverse("graph_selection_create"), {
            "selected_objects": [record.pk], "graph_context": self.context_token,
        })
        request.user = self.owner
        request.session = SessionStore(session_key=self.session_key)
        list(request.session.items())
        request._messages = FallbackStorage(request)
        return request

    def legacy_selection(self):
        """
        Restore an old deployment's session entry without creating a database bucket
        """
        TemporaryGraphSelection.objects.all().delete()
        session = self.client.session
        session[views.SELECTION_SESSION_KEY] = {
            self.token: {"owner": self.owner.pk, "objects": [self.records[0].pk]},
        }
        session.save()


class TemporarySelectionSnapshotTests(TemporarySelectionFixture, TestCase):
    """
    Cover stale session writes, legacy adoption and private selection lifetimes
    """

    def test_stale_session_saves_cannot_overwrite_another_addition(self):
        """
        Keep both successful additions after two old session snapshots are saved
        """
        first = self.request(self.records[1])
        second = self.request(self.records[2])
        self.assertEqual(views.selection_create(first).status_code, 302)
        first.session.save()
        self.assertEqual(views.selection_create(second).status_code, 302)
        second.session.save()
        current = self.request(self.records[0])
        self.assertEqual(set(views._selection_ids(current, self.token)),
                         {record.pk for record in self.records})

    def test_legacy_get_is_read_only_and_two_old_snapshots_adopt_once(self):
        """
        Keep existing links and adopt membership only during an explicit change
        """
        self.legacy_selection()
        original = dict(self.client.session[views.SELECTION_SESSION_KEY])
        response = self.client.get(reverse("selection_detail", args=[self.token]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TemporaryGraphSelection.objects.exists())
        self.assertEqual(self.client.session[views.SELECTION_SESSION_KEY], original)
        self.test_stale_session_saves_cannot_overwrite_another_addition()
        self.assertEqual(TemporaryGraphSelection.objects.count(), 1)
        self.assertEqual(self.client.session[views.SELECTION_SESSION_KEY], original)

    def test_evicted_legacy_token_cannot_return_from_an_old_session_snapshot(self):
        """
        Trust the bounded database bucket even when old session entries remain
        """
        self.legacy_selection()
        stale = self.request(self.records[1])
        for _ in range(8):
            response = self.client.post(reverse("graph_selection_create"), {
                "selected_objects": [self.records[1].pk],
            })
            self.assertEqual(response.status_code, 302)
        stale.session.save()
        self.assertEqual(self.client.get(reverse("selection_detail", args=[self.token])).status_code, 404)
        bucket = TemporaryGraphSelection.objects.get()
        self.assertEqual(len(bucket.selections), 8)
        self.assertNotIn(self.token, bucket.selections)

    def test_expired_bucket_never_falls_back_to_legacy_entries(self):
        """
        Reject expired continuations while allowing a fresh bounded selection
        """
        self.legacy_selection()
        request = self.request(self.records[1])
        self.assertEqual(views.selection_create(request).status_code, 302)
        expired = timezone.now() - timedelta(seconds=1)
        TemporaryGraphSelection.objects.update(expires_at=expired)
        response = self.client.get(reverse("selection_detail", args=[self.token]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(views.selection_create(self.request(self.records[2])).status_code, 400)
        created = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [self.records[2].pk],
        })
        self.assertEqual(created.status_code, 302)
        self.assertNotIn(self.token, TemporaryGraphSelection.objects.get().selections)

    def test_expiry_is_bounded_by_session_and_keys_are_not_stored(self):
        """
        Keep temporary storage shorter than the owning authenticated session
        """
        bucket = TemporaryGraphSelection.objects.get()
        self.assertEqual(len(bucket.session_digest), 64)
        self.assertNotIn(self.session_key, str(bucket.__dict__))
        self.assertLessEqual(bucket.expires_at, bucket.session_expires_at)
        self.assertLessEqual(bucket.expires_at, timezone.now() + timedelta(days=7))
        session = self.client.session
        deadline = timezone.now() + timedelta(minutes=20)
        session.set_expiry(deadline)
        session.save()
        self.assertEqual(views.selection_create(self.request(self.records[1])).status_code, 302)
        bucket.refresh_from_db()
        self.assertEqual(bucket.expires_at, deadline)

    def test_logout_and_new_login_cannot_reuse_the_previous_bucket(self):
        """
        Invalidate temporary navigation when authentication creates another session
        """
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("selection_detail", args=[self.token])).status_code, 404)

    def test_owner_check_rejects_a_reused_session_digest(self):
        """
        Require the bucket owner even when a request presents an existing session key
        """
        other = User.objects.create_user(username="temporary-other-owner")
        request = self.request(self.records[1])
        request.user = other
        with self.assertRaises(Http404):
            views._selection_ids(request, self.token)
        self.assertEqual(views.selection_create(request).status_code, 400)
        bucket = TemporaryGraphSelection.objects.get()
        self.assertEqual(bucket.owner_id, self.owner.pk)
        self.assertEqual(bucket.selections[self.token]["objects"], [self.records[0].pk])

    def test_cleanup_keeps_renewed_session_tombstone_and_drops_expired_session(self):
        """
        Clear old members without letting a renewed session revive its legacy token
        """
        self.legacy_selection()
        self.assertEqual(views.selection_create(self.request(self.records[1])).status_code, 302)
        expired = timezone.now() - timedelta(days=1)
        TemporaryGraphSelection.objects.update(expires_at=expired, session_expires_at=expired)
        Session.objects.filter(session_key=self.session_key).update(expire_date=timezone.now() + timedelta(days=30))
        output = StringIO()
        call_command("clear_expired_graph_selections", stdout=output)
        self.assertEqual(TemporaryGraphSelection.objects.get().selections, {})
        self.assertIn("Cleared 1", output.getvalue())
        self.assertEqual(self.client.get(reverse("selection_detail", args=[self.token])).status_code, 404)
        Session.objects.filter(session_key=self.session_key).delete()
        call_command("clear_expired_graph_selections", stdout=StringIO())
        self.assertFalse(TemporaryGraphSelection.objects.exists())

    def test_cleanup_preserves_a_bucket_changed_during_its_session_snapshot(self):
        """
        Avoid deleting a bucket updated after cleanup's live session snapshot began
        """
        from .temporary_selections import prune_expired_selections

        bucket = TemporaryGraphSelection.objects.get()

        def missing_session(*args, **kwargs):
            """
            Simulate a bucket update after the cleanup cutoff but before deletion

            Parameters
            ----------
            *args : object
                Session query arguments.
            **kwargs : object
                Session query options.

            Returns
            -------
            QuerySet
                Empty session snapshot taken before the simulated update.
            """
            TemporaryGraphSelection.objects.filter(pk=bucket.pk).update(updated_at=timezone.now())
            return Session.objects.none()

        with patch("apps.pages.temporary_selections.Session.objects.filter", side_effect=missing_session):
            self.assertEqual(prune_expired_selections(), (0, 0))
        self.assertTrue(TemporaryGraphSelection.objects.filter(pk=bucket.pk).exists())


@skipUnlessDBFeature("has_select_for_update")
class TemporarySelectionDatabaseConcurrencyTests(TemporarySelectionFixture, TransactionTestCase):
    """
    Exercise overlapping requests and real database row locks on PostgreSQL
    """

    def simultaneous_additions(self, *, create=False):
        """
        Start both requests from loaded old sessions on separate database connections

        Parameters
        ----------
        create : bool, optional
            Create new selections instead of extending the fixture selection.

        Returns
        -------
        list of int
            HTTP status for each completed mutation.
        """
        ready = Barrier(2)

        def submit(record):
            """
            Submit one already loaded browser request and save its session afterward

            Parameters
            ----------
            record : JSONData
                Member being added by this request.

            Returns
            -------
            int
                The mutation's HTTP status code.
            """
            close_old_connections()
            try:
                request = self.request(record)
                if create:
                    request.POST = request.POST.copy()
                    request.POST.pop("graph_context")
                ready.wait(timeout=10)
                response = views.selection_create(request)
                request.session.save()
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, record) for record in self.records[1:]]
            return [future.result(timeout=20) for future in futures]

    def test_parallel_additions_merge_without_lost_members(self):
        """
        Serialize two successful additions and preserve both after session saves
        """
        self.assertEqual(self.simultaneous_additions(), [302, 302])
        current = self.request(self.records[0])
        self.assertEqual(set(views._selection_ids(current, self.token)), {obj.pk for obj in self.records})

    def test_parallel_legacy_adoption_creates_one_complete_bucket(self):
        """
        Serialize the first bucket creation from two identical legacy snapshots
        """
        self.legacy_selection()
        self.assertEqual(self.simultaneous_additions(), [302, 302])
        self.assertEqual(TemporaryGraphSelection.objects.count(), 1)
        self.assertEqual(set(views._selection_ids(self.request(self.records[0]), self.token)),
                         {obj.pk for obj in self.records})

    def test_parallel_first_selections_create_one_bucket_with_both_tokens(self):
        """
        Serialize creation before the browser has any authoritative bucket row
        """
        TemporaryGraphSelection.objects.all().delete()
        self.assertEqual(self.simultaneous_additions(create=True), [302, 302])
        entries = TemporaryGraphSelection.objects.get().selections
        self.assertEqual(len(entries), 2)
        self.assertEqual({tuple(entry["objects"]) for entry in entries.values()},
                         {(self.records[1].pk,), (self.records[2].pk,)})

    def test_parallel_new_selections_keep_the_latest_eight_entries(self):
        """
        Preserve the bucket limit and both newest tokens under concurrent creation
        """
        for _ in range(7):
            self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.records[0].pk]})
        self.assertEqual(self.simultaneous_additions(create=True), [302, 302])
        entries = TemporaryGraphSelection.objects.get().selections
        self.assertEqual(len(entries), 8)
        latest = sorted(entries.values(), key=lambda entry: entry["order"])[-2:]
        self.assertEqual({tuple(entry["objects"]) for entry in latest},
                         {(self.records[1].pk,), (self.records[2].pk,)})
        self.assertNotIn(self.token, entries)

    def test_parallel_temporary_additions_cannot_exceed_capacity(self):
        """
        Let exactly one competing addition commit when only one place remains
        """
        with patch("apps.pages.research_collections.MAX_SELECTION_OBJECTS", 2):
            self.assertEqual(sorted(self.simultaneous_additions()), [302, 400])
        members = views._selection_ids(self.request(self.records[0]), self.token)
        self.assertEqual(len(members), 2)
        self.assertIn(self.records[0].pk, members)

    def test_parallel_saved_additions_cannot_exceed_capacity(self):
        """
        Exercise the saved collection row lock against two competing requests
        """
        collection = ResearchCollection.objects.create(owner=self.owner, title="Concurrent saved set")
        collection.members.add(self.records[0])
        workspace = self.client.get(reverse("collection_detail", args=[collection.pk]))
        self.context_token = workspace.context["graph_context"]
        with patch("apps.pages.research_collections.MAX_COLLECTION_OBJECTS", 2):
            self.assertEqual(sorted(self.simultaneous_additions()), [302, 400])
        self.assertEqual(collection.members.count(), 2)
        self.assertTrue(collection.members.filter(pk=self.records[0].pk).exists())
