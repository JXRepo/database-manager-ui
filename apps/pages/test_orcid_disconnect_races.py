from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.db.models.query import QuerySet
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile
from .orcid_auth import (
    ORCIDTransaction,
    complete_orcid_link,
    complete_orcid_login,
)


class ORCIDDisconnectMarkerTests(TestCase):
    """
    Check the default state of the ORCID disconnect marker
    """

    def test_new_profile_has_no_disconnect_marker(self):
        """
        A profile with no disconnect history starts without a marker
        """
        profile = AccountProfile()

        self.assertIsNone(getattr(profile, "orcid_disconnected_at", "missing"))


@override_settings(LOGIN_URL="/login/")
class ORCIDDisconnectRaceTests(TestCase):
    """
    Reject stale ORCID callbacks using real database state transitions
    """

    orcid = "0000-0002-1451-2715"

    def setUp(self):
        """
        Create a disconnected local account and a second identity owner
        """
        self.user = User.objects.create_user(username="disconnect-owner")
        self.other = User.objects.create_user(username="other-owner")
        self.disconnected_at = timezone.now()
        self.profile = AccountProfile.objects.create(
            user=self.user,
            orcid="legacy-value",
            institution="Research Institute",
            orcid_disconnected_at=self.disconnected_at,
        )
        self.other_profile = AccountProfile.objects.create(user=self.other)

    def _request(self, user=None):
        """
        Build a callback request with real session and message storage

        Parameters
        ----------
        user : User or None
            Authenticated account or None for an anonymous callback.

        Returns
        -------
        HttpRequest
            Request ready for authentication helper calls.
        """
        request = RequestFactory().get("/settings/orcid/callback/")
        SessionMiddleware(lambda request: None).process_request(request)
        request._messages = FallbackStorage(request)
        request.user = user if user is not None else AnonymousUser()
        return request

    def _link_transaction(self, created_at):
        """
        Represent a consumed link transaction from another browser session

        Parameters
        ----------
        created_at : datetime
            Time when the old browser session started its OAuth flow.

        Returns
        -------
        ORCIDTransaction
            Link transaction bound to the original local account.
        """
        return ORCIDTransaction(
            state="previous-browser-state",
            intent="link",
            user_id=self.user.pk,
            created_at=created_at.timestamp(),
            next_url="/search/",
        )

    def test_callback_started_before_disconnect_cannot_restore_identity(self):
        """
        An old callback cannot restore an identity removed in another session
        """
        request = self._request(self.user)
        old_transaction = self._link_transaction(
            self.disconnected_at - timedelta(seconds=30)
        )

        response = complete_orcid_link(request, old_transaction, self.orcid)

        self.assertEqual(response["Location"], reverse("account_settings"))
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.authenticated_orcid)
        self.assertIsNone(self.profile.orcid_authenticated_at)
        self.assertEqual(self.profile.orcid, "legacy-value")
        self.assertEqual(self.profile.institution, "Research Institute")
        self.assertEqual(
            [message.level_tag for message in get_messages(request)], ["error"]
        )

    def test_callback_started_at_disconnect_time_is_rejected(self):
        """
        Equal timestamps do not let a pending link bypass disconnect
        """
        request = self._request(self.user)
        old_transaction = self._link_transaction(self.disconnected_at)

        complete_orcid_link(request, old_transaction, self.orcid)

        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.authenticated_orcid)
        self.assertEqual(
            [message.level_tag for message in get_messages(request)], ["error"]
        )

    def test_stale_callback_is_rejected_after_a_newer_reconnection(self):
        """
        A stale callback cannot report success merely because the iD matches
        """
        linked_at = self.disconnected_at + timedelta(seconds=10)
        self.profile.authenticated_orcid = self.orcid
        self.profile.orcid_authenticated_at = linked_at
        self.profile.save(
            update_fields=["authenticated_orcid", "orcid_authenticated_at"]
        )
        request = self._request(self.user)
        old_transaction = self._link_transaction(
            self.disconnected_at - timedelta(seconds=30)
        )

        complete_orcid_link(request, old_transaction, self.orcid)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)
        self.assertEqual(self.profile.orcid_authenticated_at, linked_at)
        self.assertEqual(
            [message.level_tag for message in get_messages(request)], ["error"]
        )

    def test_callback_started_after_disconnect_can_reconnect(self):
        """
        A deliberately started later OAuth flow can reconnect the account
        """
        request = self._request(self.user)
        new_transaction = self._link_transaction(
            self.disconnected_at + timedelta(seconds=10)
        )

        complete_orcid_link(request, new_transaction, self.orcid)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.authenticated_orcid, self.orcid)
        self.assertIsNotNone(self.profile.orcid_authenticated_at)
        self.assertEqual(self.profile.orcid_disconnected_at, self.disconnected_at)
        self.assertEqual(
            [message.level_tag for message in get_messages(request)], ["success"]
        )

    def _complete_login_after_identity_change(self, change_identity):
        """
        Change real ownership immediately after the initial identity lookup

        The query still returns its real, now stale model instance. Only the
        scheduling boundary is controlled; session authentication stays real.

        Parameters
        ----------
        change_identity : callable
            Database mutation representing a concurrent disconnect or reassignment.

        Returns
        -------
        tuple[HttpRequest, HttpResponse]
            Callback request and the resulting login response.
        """
        self.profile.authenticated_orcid = self.orcid
        self.profile.orcid_authenticated_at = timezone.now()
        self.profile.save(
            update_fields=["authenticated_orcid", "orcid_authenticated_at"]
        )
        request = self._request()
        original_first = QuerySet.first
        mutation_applied = False

        def first_then_change_identity(queryset):
            """
            Apply the database mutation after resolving the original profile

            Parameters
            ----------
            queryset : QuerySet
                Actual identity lookup performed by the login helper.

            Returns
            -------
            Model or None
                Unmodified lookup result from before the database mutation.
            """
            nonlocal mutation_applied
            result = original_first(queryset)
            if (
                not mutation_applied
                and queryset.model is AccountProfile
                and result is not None
                and result.pk == self.profile.pk
            ):
                mutation_applied = True
                change_identity()
            return result

        with patch.object(QuerySet, "first", first_then_change_identity):
            response = complete_orcid_login(request, self.orcid, "/search/")

        self.assertTrue(mutation_applied)
        return request, response

    def test_login_does_not_authenticate_a_disconnected_identity(self):
        """
        Removing the binding after lookup prevents login to its former owner
        """
        def disconnect_identity():
            """
            Remove the resolved binding in the test database
            """
            AccountProfile.objects.filter(pk=self.profile.pk).update(
                authenticated_orcid=None,
                orcid_authenticated_at=None,
                orcid_disconnected_at=timezone.now(),
            )

        request, response = self._complete_login_after_identity_change(
            disconnect_identity
        )

        self.assertEqual(response["Location"], "/login/")
        self.assertNotIn("_auth_user_id", request.session)
        self.assertEqual(User.objects.count(), 2)

    def test_login_does_not_authenticate_a_reassigned_identity(self):
        """
        Moving the binding after lookup does not authenticate either owner
        """
        def reassign_identity():
            """
            Move the resolved identity to the other real profile
            """
            AccountProfile.objects.filter(pk=self.profile.pk).update(
                authenticated_orcid=None
            )
            AccountProfile.objects.filter(pk=self.other_profile.pk).update(
                authenticated_orcid=self.orcid
            )

        request, response = self._complete_login_after_identity_change(
            reassign_identity
        )

        self.assertEqual(response["Location"], "/login/")
        self.assertNotIn("_auth_user_id", request.session)
        self.other_profile.refresh_from_db()
        self.assertEqual(self.other_profile.authenticated_orcid, self.orcid)

    def test_login_does_not_authenticate_an_account_deactivated_after_lookup(self):
        """
        Deactivation between lookup and authentication prevents a new session
        """
        def deactivate_user():
            """
            Deactivate the resolved user in the test database
            """
            User.objects.filter(pk=self.user.pk).update(is_active=False)

        request, response = self._complete_login_after_identity_change(deactivate_user)

        self.assertEqual(response["Location"], "/login/")
        self.assertNotIn("_auth_user_id", request.session)

    def test_login_handles_account_deletion_after_lookup(self):
        """
        Deleting the account after lookup returns safely without logging in
        """
        def delete_user():
            """
            Delete only the resolved synthetic user from the test database
            """
            User.objects.filter(pk=self.user.pk).delete()

        request, response = self._complete_login_after_identity_change(delete_user)

        self.assertEqual(response["Location"], "/login/")
        self.assertNotIn("_auth_user_id", request.session)
