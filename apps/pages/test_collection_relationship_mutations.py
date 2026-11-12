"""
Keep manual relationship writes consistent with record removal and share revocation
"""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import close_old_connections, connection, connections, transaction
from django.test import RequestFactory, TransactionTestCase

from . import collection_relationships as relationship_views
from . import research_collections as collection_views
from . import views
from .models import CollectionRelationship, JSONData, ResearchCollection


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks and activity observations")
class RelationshipRecordMutationTests(TransactionTestCase):
    """
    Exercise deletion and revocation against an already validated relationship write
    """

    def setUp(self):
        """
        Commit a private collection using another owner's explicitly shared record
        """
        self.owner = User.objects.create_user(username="relation-mutation-owner")
        self.other = User.objects.create_user(username="relation-mutation-other")
        self.source = JSONData.objects.create(owner=self.owner, data={"title": "Owned source"})
        self.target = JSONData.objects.create(owner=self.other, data={"title": "Shared target"})
        self.target.shared_users.add(self.owner)
        self.collection = ResearchCollection.objects.create(owner=self.owner, title="Shared research")
        self.collection.members.add(self.source, self.target)

    def request(self, user, fields):
        """
        Build an authenticated form request without sharing browser session writes

        Parameters
        ----------
        user : User
            Acting record or collection owner.
        fields : dict
            Submitted form values.

        Returns
        -------
        HttpRequest
            Request accepted by normal authenticated views and message storage.
        """
        request = RequestFactory().post("/graph/", fields, HTTP_ACCEPT="application/json")
        request.user = user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def wait_for_lock(self, pid, future):
        """
        Observe an actual database wait instead of assuming thread scheduling

        Parameters
        ----------
        pid : int
            Backend process for the competing request.
        future : Future
            Request completion used to detect an unlocked mutation.

        Returns
        -------
        bool
            Whether the request is blocked on a database lock before completing.

        Raises
        ------
        AssertionError
            The worker neither waits nor completes within the bounded interval.
        """
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if future.done():
                return False
            with connection.cursor() as cursor:
                cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid])
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return True
            time.sleep(0.01)
        self.fail("The competing database request neither waited for its lock nor completed.")

    def writer_first(self, action):
        """
        Hold the writer's endpoint locks while a normal deletion or revocation starts

        Parameters
        ----------
        action : str
            Collection deletion, single or bulk record deletion, or share revocation.

        Returns
        -------
        tuple
            Whether the mutator waited, and both completed HTTP statuses.
        """
        checked = Event()
        continue_writer = Event()
        mutation_started = Event()
        backend = {}
        validate_members = relationship_views._validate_members

        def pause_validated_writer(*args, **kwargs):
            """
            Pause after real access checks while keeping the transaction locks

            Parameters
            ----------
            *args, **kwargs : object
                Arguments forwarded unchanged to the real endpoint validator.
            """
            validate_members(*args, **kwargs)
            checked.set()
            if not continue_writer.wait(10):
                raise RuntimeError("The validated relationship writer was not released.")

        def save():
            """
            Save one explicit relationship using its own database connection

            Returns
            -------
            int
                Actual HTTP response status.
            """
            close_old_connections()
            try:
                return relationship_views.collection_relationship_save(self.request(self.owner, {
                    "source": self.source.pk, "target": self.target.pk, "label": "Uses reference",
                }), self.collection.pk).status_code
            finally:
                connections.close_all()

        def mutate():
            """
            Run the existing owner action while the graph writer holds its locks

            Returns
            -------
            int
                Actual HTTP response status after the transaction commits.
            """
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend["pid"] = cursor.fetchone()[0]
                mutation_started.set()
                if action == "collection_delete":
                    response = collection_views.collection_delete(self.request(self.owner, {}), self.collection.pk)
                elif action == "object_delete":
                    response = views.json_data_delete_view(self.request(self.other, {}), self.target.pk)
                elif action == "bulk_delete":
                    response = views.delete_selected_my_data_objects_view(self.request(self.other, {
                        "selected_objects": [self.target.pk],
                    }))
                else:
                    response = views.json_data_sharing_view(self.request(self.other, {
                        "action": "remove_user", "user_id": self.owner.pk,
                    }), self.target.pk)
                return response.status_code
            finally:
                connections.close_all()

        with patch.object(relationship_views, "_validate_members", side_effect=pause_validated_writer), \
                ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(save)
            try:
                self.assertTrue(checked.wait(10), "Writer did not reach its access checks.")
                mutation = executor.submit(mutate)
                self.assertTrue(mutation_started.wait(10), "Mutation did not start.")
                waited = self.wait_for_lock(backend["pid"], mutation)
            finally:
                continue_writer.set()
            return waited, writer.result(timeout=10), mutation.result(timeout=10)

    def test_collection_deletion_waits_before_collecting_new_relationships(self):
        """
        Delete the connection committed by a writer before cascading its collection
        """
        self.assertEqual(self.writer_first("collection_delete"), (True, 200, 302))
        self.assertFalse(ResearchCollection.objects.filter(pk=self.collection.pk).exists())
        self.assertFalse(CollectionRelationship.objects.exists())
        self.assertTrue(JSONData.objects.filter(pk=self.source.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=self.target.pk).exists())

    def test_record_deletion_waits_before_collecting_new_relationships(self):
        """
        Cascade a newly committed connection without a foreign key failure
        """
        self.assertEqual(self.writer_first("object_delete"), (True, 200, 302))
        self.assertFalse(JSONData.objects.filter(pk=self.target.pk).exists())
        self.assertFalse(CollectionRelationship.objects.exists())
        self.assertTrue(ResearchCollection.objects.filter(pk=self.collection.pk).exists())

    def test_bulk_record_deletion_waits_before_collecting_new_relationships(self):
        """
        Apply the same consistent cascade when removing selected owned data objects
        """
        self.assertEqual(self.writer_first("bulk_delete"), (True, 200, 302))
        self.assertFalse(JSONData.objects.filter(pk=self.target.pk).exists())
        self.assertFalse(CollectionRelationship.objects.exists())

    def test_share_revocation_waits_for_a_previously_authorized_writer(self):
        """
        Allow an earlier writer to commit then hide its connection after revocation
        """
        self.assertEqual(self.writer_first("revoke"), (True, 200, 302))
        self.assertEqual(CollectionRelationship.objects.count(), 1)
        self.assertFalse(self.target.shared_users.filter(pk=self.owner.pk).exists())
        self.assertFalse(relationship_views.accessible_relationships(self.owner, self.collection).exists())

    def test_revocation_that_wins_the_lock_is_rechecked_after_the_writer_waits(self):
        """
        Reject a stale sharing snapshot once the prior revocation transaction commits
        """
        revocation_locked = Event()
        continue_revocation = Event()
        writer_started = Event()
        backend = {}

        def revoke():
            """
            Hold the object lock before a normal share removal on the same connection

            Returns
            -------
            int
                Actual revocation HTTP status after committing its lock.
            """
            close_old_connections()
            try:
                with transaction.atomic():
                    JSONData.objects.select_for_update().get(pk=self.target.pk)
                    revocation_locked.set()
                    if not continue_revocation.wait(10):
                        raise RuntimeError("The locked revocation was not released.")
                    response = views.json_data_sharing_view(self.request(self.other, {
                        "action": "remove_user", "user_id": self.owner.pk,
                    }), self.target.pk)
                return response.status_code
            finally:
                connections.close_all()

        def save():
            """
            Begin permission validation while the old share is still visible

            Returns
            -------
            int
                Save response after waiting for the revocation transaction.
            """
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend["pid"] = cursor.fetchone()[0]
                writer_started.set()
                return relationship_views.collection_relationship_save(self.request(self.owner, {
                    "source": self.source.pk, "target": self.target.pk, "label": "Stale permission",
                }), self.collection.pk).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            revoker = executor.submit(revoke)
            try:
                self.assertTrue(revocation_locked.wait(10), "Revoker did not obtain its object lock.")
                writer = executor.submit(save)
                self.assertTrue(writer_started.wait(10), "Writer did not start.")
                self.assertTrue(self.wait_for_lock(backend["pid"], writer))
            finally:
                continue_revocation.set()
            self.assertEqual(revoker.result(timeout=10), 302)
            self.assertEqual(writer.result(timeout=10), 400)
        self.assertFalse(CollectionRelationship.objects.exists())
        self.assertFalse(self.target.shared_users.filter(pk=self.owner.pk).exists())
