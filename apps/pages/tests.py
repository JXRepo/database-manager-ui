import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.dyn_api.helpers import validate_json

from .context_processors import shared_data_notifications
from .models import AccountProfile, DataNotification, JSONData
from .orcid_auth import ORCID_TRANSACTION_SESSION_KEY
from .views import (
    _build_detail_rows,
    _ensure_required_detail_rows,
    _build_mechanical_bc_items,
    _extract_plot_variables,
    _filter_visualized_detail_rows,
    _group_detail_rows,
    _prepare_list_object,
)


class JSONDataSharingTests(TestCase):
    """
    Test data object sharing rules
    """

    def setUp(self):
        """
        Create users used by sharing tests
        """
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password",
        )
        self.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="password",
        )
        self.factory = RequestFactory()

    def _build_valid_upload_object(self, identifier, shared_with=None, phase=None):
        """
        Build a valid upload object for upload workflow tests

        Parameters
        ----------
        identifier : str
            Identifier to place in the uploaded JSON object.
        shared_with : list, optional
            Sharing metadata to place in the uploaded JSON object.
        phase : list or str, optional
            Phase metadata to place in the uploaded JSON object.

        Returns
        -------
        dict
            JSON object with all required top-level fields.
        """
        if shared_with is None:
            shared_with = [{"access_type": "c"}]

        if phase is None:
            phase = [{"phase_identifier": "Copper"}]

        return {
            "identifier": identifier,
            "title": f"Stress-Strain Analysis {identifier}",
            "creator": ["Owner, Test"],
            "creator_affiliation": ["ICAMS"],
            "date": "2026-06-15",
            "shared_with": shared_with,
            "rights": "Creative Commons Attribution 4.0 International",
            "rights_holder": ["Owner, Test"],
            "software": "Abaqus CAE",
            "software_version": "6.14",
            "system": "Linux",
            "system_version": "Ubuntu 16.04",
            "processor_specifications": "Intel64",
            "input_path": "inputs",
            "results_path": "results",
            "RVE_size": [1, 1, 1],
            "RVE_continuity": True,
            "discretization_type": "Structured",
            "discretization_unit_size": [1, 1, 1],
            "discretization_count": 1,
            "mechanical_BC": [
                {
                    "vertex_list": ["V000"],
                    "constraints": ["fixed", "loaded", "free"],
                    "loading_type": "force",
                    "loading_mode": "static",
                    "applied_load": [
                        {
                            "magnitude": 10,
                            "frequency": 0,
                            "duration": 1,
                            "R": 0,
                        }
                    ],
                }
            ],
            "phase": phase,
            "stress": {"stress_11": [0, 1]},
            "total_strain": {"strain_11": [0, 0.1]},
            "units": {"Stress": "MPa", "Strain": 1},
        }

    def _post_upload_object(self, data):
        """
        Upload one JSON object through the upload view

        Parameters
        ----------
        data : dict
            JSON object to upload.

        Returns
        -------
        HttpResponse
            Upload view response.
        """
        uploaded_file = SimpleUploadedFile(
            "object.json",
            json.dumps(data).encode("utf-8"),
            content_type="application/json",
        )
        return self.client.post(
            reverse("upload_json"),
            {"file": uploaded_file},
        )

    def _post_assistant(self, payload):
        """
        Post one JSON payload to the FAIR assistant endpoint

        Parameters
        ----------
        payload : dict
            Assistant request payload.

        Returns
        -------
        HttpResponse
            Assistant endpoint response.
        """
        return self.client.post(
            reverse("fair_assistant_ask"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_upload_validation_allows_empty_optional_top_level_fields(self):
        """
        Upload validation only rejects empty required top-level fields
        """
        data = self._build_valid_upload_object("optional-empty")
        data["optional_note"] = ""

        valid_data, errors = validate_json([data])

        self.assertEqual(valid_data, [data])
        self.assertEqual(errors, [])

    def test_upload_validation_rejects_empty_required_top_level_fields(self):
        """
        Upload validation rejects empty required top-level fields
        """
        data = self._build_valid_upload_object("required-empty")
        data["title"] = ""

        valid_data, errors = validate_json([data])

        self.assertEqual(valid_data, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("empty required field: title", errors[0])

    def test_private_data_object_can_be_shared_with_specific_user(self):
        """
        Private data objects can be added to a user's shared list
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "private-object", "phase": "alpha"},
            access_type="c",
        )
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("json_data_sharing", args=[obj.pk]),
            {
                "action": "add_user",
                "share_user": "viewer",
            },
        )

        self.assertRedirects(response, reverse("json_data_detail", args=[obj.pk]))
        self.assertTrue(obj.shared_users.filter(pk=self.viewer.pk).exists())

    def test_private_data_object_cannot_be_shared_by_email(self):
        """
        Private data objects cannot be shared by email address
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "private-email-object", "phase": "alpha"},
            access_type="c",
        )
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("json_data_sharing", args=[obj.pk]),
            {
                "action": "add_user",
                "share_user": "viewer@example.com",
            },
        )

        self.assertRedirects(response, reverse("json_data_detail", args=[obj.pk]))
        self.assertFalse(obj.shared_users.filter(pk=self.viewer.pk).exists())

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("No user was found with that username." in message for message in messages))

    def test_public_data_object_cannot_be_shared_with_specific_user(self):
        """
        Public data objects are not added to a user's shared list
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "public-object", "phase": "alpha"},
            access_type="all",
        )
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("json_data_sharing", args=[obj.pk]),
            {
                "action": "add_user",
                "share_user": "viewer",
            },
        )

        self.assertRedirects(response, reverse("json_data_detail", args=[obj.pk]))
        self.assertFalse(obj.shared_users.filter(pk=self.viewer.pk).exists())

    def test_shared_with_me_lists_private_shared_data_only(self):
        """
        Shared with Me excludes public objects even when they have shared users
        """
        private_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "private-object", "phase": "alpha"},
            access_type="c",
        )
        public_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "public-object", "phase": "alpha"},
            access_type="all",
        )
        private_obj.shared_users.add(self.viewer)
        public_obj.shared_users.add(self.viewer)
        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("share"))

        object_ids = [
            obj.id
            for obj in response.context["shared_with_me_objects"]
        ]
        self.assertIn(private_obj.id, object_ids)
        self.assertNotIn(public_obj.id, object_ids)

    def test_sharing_history_lists_data_shared_by_current_user(self):
        """
        Sharing history lists data objects the signed-in user shared
        """
        shared_object = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "owner-shared-history", "phase": "alpha"},
            access_type="c",
        )
        shared_object.shared_users.add(self.viewer)
        DataNotification.objects.create(
            recipient=self.viewer,
            actor=self.owner,
            data_object=shared_object,
            notification_type=DataNotification.TYPE_SHARED_DATA,
            message="owner shared owner-shared-history with you.",
        )
        incoming_object = JSONData.objects.create(
            owner=self.viewer,
            data={"identifier": "incoming-shared-history", "phase": "beta"},
            access_type="c",
        )
        DataNotification.objects.create(
            recipient=self.owner,
            actor=self.viewer,
            data_object=incoming_object,
            notification_type=DataNotification.TYPE_SHARED_DATA,
            message="viewer shared incoming-shared-history with you.",
        )
        self.client.login(username="owner", password="password")

        response = self.client.get(reverse("share"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared with Me")
        self.assertContains(response, "Sharing History")
        self.assertContains(response, "owner-shared-history")
        self.assertContains(response, "viewer")
        event_ids = [
            event.data_object_id
            for event in response.context["share_events"]
        ]
        self.assertIn(shared_object.id, event_ids)
        self.assertNotIn(incoming_object.id, event_ids)

    def test_shared_notifications_count_private_shared_data_only(self):
        """
        Shared notifications count unread private share notifications only
        """
        private_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "private-object", "phase": "alpha"},
            access_type="c",
        )
        public_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "public-object", "phase": "alpha"},
            access_type="all",
        )
        private_obj.shared_users.add(self.viewer)
        public_obj.shared_users.add(self.viewer)
        private_notification = DataNotification.objects.create(
            recipient=self.viewer,
            actor=self.owner,
            data_object=private_obj,
            message="owner shared private-object with you.",
        )
        DataNotification.objects.create(
            recipient=self.viewer,
            actor=self.owner,
            data_object=public_obj,
            message="owner shared public-object with you.",
        )
        DataNotification.objects.create(
            recipient=self.viewer,
            actor=self.owner,
            data_object=private_obj,
            message="old read notification.",
            is_read=True,
        )

        request = self.factory.get("/")
        request.user = self.viewer

        context = shared_data_notifications(request)

        self.assertEqual(context["shared_data_count"], 1)
        self.assertEqual(
            context["shared_data_notifications"][0]["notification_id"],
            private_notification.id,
        )
        self.assertEqual(
            context["shared_data_notifications"][0]["data_object_id"],
            private_obj.id,
        )

    def test_manual_share_creates_unread_notification(self):
        """
        Sharing a private object creates an unread notification
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "notify-object", "phase": "alpha"},
            access_type="c",
        )
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("json_data_sharing", args=[obj.pk]),
            {
                "action": "add_user",
                "share_user": "viewer",
            },
        )

        self.assertRedirects(response, reverse("json_data_detail", args=[obj.pk]))
        notification = DataNotification.objects.get(
            recipient=self.viewer,
            actor=self.owner,
            data_object=obj,
        )
        self.assertFalse(notification.is_read)
        self.assertIn("notify-object", notification.message)

    def test_long_unicode_manual_share_notification_fits_message_field(self):
        """
        Manual sharing truncates only the Unicode display title
        """
        long_identifier = "显微组织" * 100
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": long_identifier, "phase": "alpha"},
            access_type="c",
        )
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("json_data_sharing", args=[obj.pk]),
            {
                "action": "add_user",
                "share_user": "viewer",
            },
        )

        self.assertRedirects(response, reverse("json_data_detail", args=[obj.pk]))
        notification = DataNotification.objects.get(
            recipient=self.viewer,
            actor=self.owner,
            data_object=obj,
        )
        maximum_length = DataNotification._meta.get_field("message").max_length
        prefix = f"{self.owner.username} shared "
        suffix = " with you."
        title_budget = maximum_length - len(prefix) - len(suffix)

        self.assertLessEqual(len(notification.message), maximum_length)
        self.assertTrue(notification.message.startswith(prefix))
        self.assertTrue(notification.message.endswith(suffix))
        self.assertEqual(
            notification.message[len(prefix):-len(suffix)],
            long_identifier[:title_budget],
        )

    def test_notification_open_marks_notification_read(self):
        """
        Opening a notification marks it read and redirects to detail
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "open-notification-object", "phase": "alpha"},
            access_type="c",
        )
        obj.shared_users.add(self.viewer)
        notification = DataNotification.objects.create(
            recipient=self.viewer,
            actor=self.owner,
            data_object=obj,
            message="owner shared open-notification-object with you.",
        )
        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("notification_open", args=[notification.pk]))

        self.assertRedirects(response, reverse("json_data_detail", args=[obj.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_notifications_page_lists_user_notifications(self):
        """
        Notifications page lists notifications for the signed-in user
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "listed-notification-object", "phase": "alpha"},
            access_type="c",
        )
        obj.shared_users.add(self.viewer)
        notification = DataNotification.objects.create(
            recipient=self.viewer,
            actor=self.owner,
            data_object=obj,
            message="owner shared listed-notification-object with you.",
        )
        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "listed-notification-object")
        self.assertContains(response, reverse("notification_open", args=[notification.pk]))

    def test_live_data_endpoint_returns_public_objects_only(self):
        """
        Live data endpoint excludes even accessible private objects

        Own and shared private data must stay out of the public activity feed.
        """
        own_private_obj = JSONData.objects.create(
            owner=self.viewer,
            data={"identifier": "own-private-object", "phase": "alpha"},
            access_type="c",
        )
        own_public_obj = JSONData.objects.create(
            owner=self.viewer,
            data={"identifier": "own-public-object", "phase": "alpha"},
            access_type="all",
        )
        public_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "public-object", "phase": "alpha"},
            access_type="all",
        )
        shared_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "shared-object", "phase": "alpha"},
            access_type="c",
        )
        private_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "private-object", "phase": "alpha"},
            access_type="c",
        )
        shared_obj.shared_users.add(self.viewer)

        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("search_live_data_objects"))
        objects = response.json()["objects"]
        objects_by_id = {item["id"]: item for item in objects}
        object_ids = {item["id"] for item in objects}

        self.assertEqual(response.status_code, 200)
        self.assertEqual(object_ids, {own_public_obj.id, public_obj.id})
        self.assertEqual(response.json().get("total_count"), 2)
        self.assertNotIn(own_private_obj.id, object_ids)
        self.assertNotIn(shared_obj.id, object_ids)
        self.assertNotIn(private_obj.id, object_ids)
        self.assertEqual(objects_by_id[own_public_obj.id]["access_badges"], ["Public"])
        self.assertEqual(objects_by_id[public_obj.id]["access_badges"], ["Public"])
        self.assertEqual(objects_by_id[public_obj.id]["access"], "Public")
        self.assertEqual(objects_by_id[public_obj.id]["display_name"], "public-object")
        self.assertEqual(objects_by_id[public_obj.id]["identifier"], "public-object")
        self.assertEqual(objects_by_id[public_obj.id]["owner"], "owner")
        self.assertEqual(
            objects_by_id[public_obj.id]["detail_url"],
            reverse("json_data_detail", args=[public_obj.pk]),
        )
        self.assertTrue(objects_by_id[public_obj.id]["uploaded_at"])

    def test_live_data_endpoint_removes_newly_private_object_on_next_poll(self):
        """
        A public object disappears after its owner makes it private

        Polling must recheck public visibility even for the object's owner.
        """
        obj = JSONData.objects.create(
            owner=self.viewer,
            data={"identifier": "changed-access-object", "phase": "alpha"},
            access_type="all",
        )
        self.client.force_login(self.viewer)
        url = reverse("search_live_data_objects")

        first_response = self.client.get(url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual([item["id"] for item in first_response.json()["objects"]], [obj.pk])
        self.assertEqual(first_response.json().get("total_count"), 1)

        obj.access_type = "c"
        obj.save(update_fields=["access_type"])
        next_response = self.client.get(url)

        self.assertEqual(next_response.status_code, 200)
        self.assertEqual(next_response.json()["objects"], [])
        self.assertEqual(next_response.json().get("total_count"), 0)

    def test_live_data_endpoint_limits_public_objects_after_filtering_private_uploads(self):
        """
        Recent private uploads do not displace the latest twenty public objects

        The result limit applies to public objects, not all accessible uploads.
        """
        public_ids = []
        for index in range(21):
            obj = JSONData.objects.create(
                owner=self.owner,
                data={"identifier": f"public-object-{index}", "phase": "alpha"},
                access_type="all",
            )
            public_ids.append(obj.pk)
        for index in range(21):
            JSONData.objects.create(
                owner=self.viewer,
                data={"identifier": f"private-object-{index}", "phase": "alpha"},
                access_type="c",
            )
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("search_live_data_objects"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["objects"]],
            list(reversed(public_ids[1:])),
        )
        self.assertEqual(response.json().get("total_count"), 21)

    def test_live_data_endpoint_orders_equal_timestamps_by_latest_object(self):
        """
        Simultaneous uploads retain a stable newest first order

        The object ID resolves ties in the upload timestamp between polls.
        """
        older_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "older-public-object", "phase": "alpha"},
            access_type="all",
        )
        newer_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "newer-public-object", "phase": "alpha"},
            access_type="all",
        )
        JSONData.objects.filter(pk=newer_obj.pk).update(uploaded_at=older_obj.uploaded_at)
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("search_live_data_objects"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["objects"]],
            [newer_obj.pk, older_obj.pk],
        )

    def test_live_data_endpoint_requires_login(self):
        """
        Anonymous live feed requests are redirected to login

        The public activity feed remains part of the signed in search page.
        """
        url = reverse("search_live_data_objects")

        response = self.client.get(url)

        self.assertRedirects(response, f"{settings.LOGIN_URL}?next={url}")

    def test_prepared_summary_access_keeps_private_badge_when_shared(self):
        """
        Summary fields show both Private and Shared for shared private data
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "shared-private-object", "phase": "alpha"},
            access_type="c",
        )
        obj.shared_users.add(self.viewer)

        prepared_obj = _prepare_list_object(obj)
        access_field = next(
            field
            for field in prepared_obj.summary_fields
            if field.get("type") == "access"
        )

        self.assertEqual(access_field["badges"], ["Private", "Shared"])

    def test_owner_detail_breadcrumb_uses_my_data_label(self):
        """
        Owner detail page breadcrumb points back to My Data
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "breadcrumb-object", "phase": "alpha"},
            access_type="c",
        )
        self.client.login(username="owner", password="password")

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))

        self.assertEqual(response.context["detail_breadcrumb_label"], "My Data")
        self.assertEqual(response.context["detail_back_url_name"], "json_data_list")

    def test_shared_detail_breadcrumb_uses_share_label(self):
        """
        Shared detail page breadcrumb points back to Share
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "shared-breadcrumb-object", "phase": "alpha"},
            access_type="c",
        )
        obj.shared_users.add(self.viewer)
        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))

        self.assertEqual(response.context["detail_breadcrumb_label"], "Share")
        self.assertEqual(response.context["detail_back_url_name"], "share")

    def test_account_settings_updates_username_and_email(self):
        """
        Account settings let a signed-in user update profile fields
        """
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("account_settings"),
            {
                "username": "updated-owner",
                "email": "updated-owner@example.com",
            },
        )

        self.assertRedirects(response, reverse("account_settings"))
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "updated-owner")
        self.assertEqual(self.owner.email, "updated-owner@example.com")

    def test_account_settings_updates_institution_and_ignores_orcid(self):
        """
        Account settings save institution but ignore a forged ORCID field
        """
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("account_settings"),
            {
                "username": "owner",
                "email": "owner@example.com",
                "institution": "ICAMS",
                "orcid": "0000-0002-1451-2715",
            },
        )

        self.assertRedirects(response, reverse("account_settings"))
        profile = AccountProfile.objects.get(user=self.owner)
        self.assertEqual(profile.institution, "ICAMS")
        self.assertEqual(profile.orcid, "")

    @override_settings(
        ORCID_CLIENT_ID="APP-TEST",
        ORCID_CLIENT_SECRET="secret",
        ORCID_BASE_URL="https://sandbox.orcid.org",
    )
    def test_orcid_connect_redirects_to_orcid_authorization(self):
        """
        ORCID connect starts the official authorization flow
        """
        self.client.login(username="owner", password="password")

        response = self.client.get(reverse("orcid_connect"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response["Location"].startswith(
                "https://sandbox.orcid.org/oauth/authorize?"
            )
        )
        self.assertIn("client_id=APP-TEST", response["Location"])
        self.assertIn("response_type=code", response["Location"])
        self.assertIn("scope=%2Fauthenticate", response["Location"])
        transaction = self.client.session[ORCID_TRANSACTION_SESSION_KEY]
        self.assertEqual(transaction["intent"], "link")
        self.assertEqual(transaction["user_id"], self.owner.pk)

    @override_settings(
        ORCID_CLIENT_ID="APP-TEST",
        ORCID_CLIENT_SECRET="secret",
        ORCID_BASE_URL="https://sandbox.orcid.org",
    )
    @patch("apps.pages.views._exchange_orcid_authorization_code")
    def test_orcid_connect_callback_sets_only_verified_identity(self, mock_exchange):
        """
        A successful Connect callback verifies ORCID without changing legacy data
        """
        mock_exchange.return_value = {
            "access_token": "provider-token",
            "orcid": "0000-0002-1451-2715",
            "name": "Researcher",
            "token_type": "bearer",
        }
        profile = AccountProfile.objects.create(
            user=self.owner,
            orcid="legacy-orcid-value",
        )
        self.client.login(username="owner", password="password")
        start_response = self.client.get(reverse("orcid_connect"))
        self.assertEqual(start_response.status_code, 302)
        transaction = self.client.session[ORCID_TRANSACTION_SESSION_KEY]

        response = self.client.get(
            reverse("orcid_callback"),
            {
                "code": "auth-code",
                "state": transaction["state"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_settings"))
        profile.refresh_from_db()
        self.assertEqual(profile.orcid, "legacy-orcid-value")
        self.assertEqual(
            profile.authenticated_orcid,
            "0000-0002-1451-2715",
        )
        self.assertIsNotNone(profile.orcid_authenticated_at)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.owner.pk)
        self.assertNotIn("provider-token", repr(dict(self.client.session)))
        mock_exchange.assert_called_once_with(
            "auth-code",
            "http://testserver/settings/orcid/callback/",
        )

    def test_account_settings_rejects_duplicate_username(self):
        """
        Account settings do not allow duplicate usernames
        """
        self.client.login(username="owner", password="password")

        response = self.client.post(
            reverse("account_settings"),
            {
                "username": "viewer",
                "email": "owner-new@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "owner")
        self.assertContains(response, "A user with that username already exists.")

    def test_user_menu_links_to_real_account_pages(self):
        """
        User menu links point to implemented account pages
        """
        self.client.login(username="owner", password="password")

        response = self.client.get(reverse("search"))

        self.assertContains(response, reverse("account_settings"))
        self.assertContains(response, reverse("share"))
        self.assertContains(response, reverse("password_change"))
        self.assertNotContains(response, reverse("shared_with_me"))
        self.assertNotContains(response, reverse("sharing_history"))
        self.assertNotContains(response, '<a href="#" class="dropdown-item">')

    def test_my_data_bulk_export_includes_owned_objects_only(self):
        """
        My Data bulk export only exports objects owned by the current user
        """
        own_obj = JSONData.objects.create(
            owner=self.viewer,
            data={"identifier": "own-object", "phase": "alpha"},
            access_type="c",
        )
        other_public_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "public-object", "phase": "alpha"},
            access_type="all",
        )
        shared_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "shared-object", "phase": "alpha"},
            access_type="c",
        )
        shared_obj.shared_users.add(self.viewer)

        self.client.login(username="viewer", password="password")

        response = self.client.post(
            reverse("export_selected_my_data_objects"),
            {
                "selected_objects": [
                    str(own_obj.id),
                    str(other_public_obj.id),
                    str(shared_obj.id),
                ],
            },
        )
        exported_data = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(exported_data, [own_obj.data])

    def test_my_data_bulk_delete_removes_owned_objects_only(self):
        """
        My Data bulk delete only removes objects owned by the current user
        """
        own_obj = JSONData.objects.create(
            owner=self.viewer,
            data={"identifier": "own-object", "phase": "alpha"},
            access_type="c",
        )
        other_public_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "public-object", "phase": "alpha"},
            access_type="all",
        )
        shared_obj = JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "shared-object", "phase": "alpha"},
            access_type="c",
        )
        shared_obj.shared_users.add(self.viewer)

        self.client.login(username="viewer", password="password")

        response = self.client.post(
            reverse("delete_selected_my_data_objects"),
            {
                "selected_objects": [
                    str(own_obj.id),
                    str(other_public_obj.id),
                    str(shared_obj.id),
                ],
            },
        )

        self.assertRedirects(response, reverse("json_data_list"))
        self.assertFalse(JSONData.objects.filter(pk=own_obj.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=other_public_obj.pk).exists())
        self.assertTrue(JSONData.objects.filter(pk=shared_obj.pk).exists())

    def test_upload_reads_private_shared_username_from_json(self):
        """
        Upload links private shared_with username metadata to shared users
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "shared-upload-object",
            shared_with=[
                {
                    "access_type": "c",
                    "username": "viewer",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        obj = JSONData.objects.get(data__identifier="shared-upload-object")
        self.assertEqual(obj.access_type, "c")
        self.assertTrue(obj.shared_users.filter(pk=self.viewer.pk).exists())
        self.assertTrue(
            DataNotification.objects.filter(
                recipient=self.viewer,
                actor=self.owner,
                data_object=obj,
                is_read=False,
            ).exists()
        )

    def test_upload_keeps_private_when_username_key_is_absent(self):
        """
        Upload saves c access data as private when username is absent
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "plain-private-object",
            shared_with=[
                {
                    "access_type": "c",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        obj = JSONData.objects.get(data__identifier="plain-private-object")
        self.assertEqual(obj.access_type, "c")
        self.assertEqual(obj.shared_users.count(), 0)

    def test_upload_rejects_unknown_shared_username(self):
        """
        Upload rejects private sharing when username does not exist
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "unknown-share-object",
            shared_with=[
                {
                    "access_type": "c",
                    "username": "missing-user",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(
            JSONData.objects.filter(data__identifier="unknown-share-object").exists()
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Unknown shared users" in message for message in messages))
        self.assertTrue(any("missing-user" in message for message in messages))

    def test_upload_rejects_email_as_shared_username(self):
        """
        Upload rejects email values in the shared_with username field
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "email-share-object",
            shared_with=[
                {
                    "access_type": "c",
                    "username": "viewer@example.com",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(
            JSONData.objects.filter(data__identifier="email-share-object").exists()
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Unknown shared users" in message for message in messages))
        self.assertTrue(any("viewer@example.com" in message for message in messages))

    def test_upload_rejects_empty_shared_username(self):
        """
        Upload rejects shared_with username when the value is empty
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "empty-share-object",
            shared_with=[
                {
                    "access_type": "c",
                    "username": "",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(
            JSONData.objects.filter(data__identifier="empty-share-object").exists()
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Empty values" in message for message in messages))
        self.assertTrue(any("empty username" in message for message in messages))

    def test_upload_rejects_empty_shared_access_type(self):
        """
        Upload rejects shared_with access_type when the value is empty
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "empty-access-object",
            shared_with=[
                {
                    "access_type": "",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(
            JSONData.objects.filter(data__identifier="empty-access-object").exists()
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Empty values" in message for message in messages))
        self.assertTrue(any("empty access_type" in message for message in messages))

    def test_upload_rejects_invalid_access_type(self):
        """
        Upload rejects shared_with access_type values other than all or c
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object(
            "invalid-access-object",
            shared_with=[
                {
                    "access_type": "private",
                }
            ],
        )

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(
            JSONData.objects.filter(data__identifier="invalid-access-object").exists()
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Invalid access metadata" in message for message in messages))
        self.assertTrue(any("invalid access_type" in message for message in messages))

    def test_upload_rejects_empty_required_top_level_values(self):
        """
        Upload rejects empty required top-level key values
        """
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object("empty-title-object")
        upload_data["title"] = ""
        upload_data["description"] = ""

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertFalse(
            JSONData.objects.filter(data__identifier="empty-title-object").exists()
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("Empty values" in message for message in messages))
        self.assertTrue(any("title" in message for message in messages))
        self.assertFalse(any("description" in message for message in messages))

    def test_upload_rejects_existing_identifier(self):
        """
        Upload skips data objects whose identifier already exists
        """
        JSONData.objects.create(
            owner=self.owner,
            data={"identifier": "duplicate-object", "phase": "Copper"},
            access_type="c",
        )
        self.client.login(username="owner", password="password")
        upload_data = self._build_valid_upload_object("duplicate-object")

        response = self._post_upload_object(upload_data)

        self.assertRedirects(response, reverse("upload_json"))
        self.assertEqual(
            JSONData.objects.filter(data__identifier="duplicate-object").count(),
            1,
        )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("already exists" in message for message in messages))

    def test_upload_saves_valid_object_and_reports_schema_invalid_object(self):
        """
        Schema errors still allow other valid objects in the file to save
        """
        self.client.login(username="owner", password="password")
        valid_object = self._build_valid_upload_object("valid-object")
        invalid_object = {"identifier": "invalid-object"}

        response = self._post_upload_object([valid_object, invalid_object])

        self.assertRedirects(response, reverse("upload_json"))
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertTrue(
            JSONData.objects.filter(data__identifier="valid-object").exists()
        )
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("partially successful" in message for message in messages))
        self.assertTrue(any("Object 2 in this file" in message for message in messages))
        self.assertTrue(any('data-upload-category="missing_required"' in message for message in messages))

    def test_search_filters_by_phase(self):
        """
        Search can filter accessible objects by phase
        """
        copper_obj = JSONData.objects.create(
            owner=self.viewer,
            data=self._build_valid_upload_object(
                "copper-object",
                phase=[{"phase_identifier": "Copper"}],
            ),
            access_type="c",
        )
        nickel_obj = JSONData.objects.create(
            owner=self.viewer,
            data=self._build_valid_upload_object(
                "nickel-object",
                phase=[{"phase_identifier": "Nickel"}],
            ),
            access_type="c",
        )
        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("search"), {"phase": "Copper"})
        object_ids = [obj.id for obj in response.context["data_objects"]]

        self.assertIn(copper_obj.id, object_ids)
        self.assertNotIn(nickel_obj.id, object_ids)

    def test_assistant_upload_guidance_mentions_username(self):
        """
        Assistant explains upload sharing metadata
        """
        self.client.login(username="owner", password="password")

        response = self._post_assistant(
            {
                "page": "upload",
                "question": "How should I write shared_with?",
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("username", payload["answer"])
        self.assertTrue(payload["suggestions"])

    def test_assistant_detail_summarizes_accessible_object(self):
        """
        Assistant summarizes an object the user can access
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data=self._build_valid_upload_object("assistant-object"),
            access_type="c",
        )
        self.client.login(username="owner", password="password")

        response = self._post_assistant(
            {
                "page": "detail",
                "object_id": obj.pk,
                "question": "Summarize this data",
            }
        )

        self.assertEqual(response.status_code, 200)
        answer = response.json()["answer"]
        self.assertIn("assistant-object", answer)
        self.assertIn("Abaqus", answer)

    def test_assistant_blocks_inaccessible_object(self):
        """
        Assistant does not expose private objects to other users
        """
        obj = JSONData.objects.create(
            owner=self.owner,
            data=self._build_valid_upload_object("private-assistant-object"),
            access_type="c",
        )
        self.client.login(username="viewer", password="password")

        response = self._post_assistant(
            {
                "page": "detail",
                "object_id": obj.pk,
                "question": "Summarize this data",
            }
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Data object not found.")

    def test_assistant_rejects_empty_question(self):
        """
        Assistant rejects empty questions
        """
        self.client.login(username="owner", password="password")

        response = self._post_assistant(
            {
                "page": "upload",
                "question": "   ",
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("question", response.json()["error"])

    def test_mechanical_bc_items_include_unused_vertices(self):
        """
        Mechanical boundary condition items include free unused vertices
        """
        data = self._build_valid_upload_object("bc-object")

        items = _build_mechanical_bc_items(data)
        items_by_vertex = {item["vertex"]: item for item in items}

        self.assertEqual(len(items_by_vertex), 8)
        self.assertTrue(items_by_vertex["V000"]["is_defined"])
        self.assertFalse(items_by_vertex["V111"]["is_defined"])
        self.assertEqual(
            [axis["status"] for axis in items_by_vertex["V111"]["axes"]],
            ["free", "free", "free"],
        )

    def test_mechanical_bc_items_include_full_load_details(self):
        """
        Loaded axes keep magnitude, frequency, duration, and R details
        """
        data = self._build_valid_upload_object("bc-load-details")

        items = _build_mechanical_bc_items(data)
        v000 = next(item for item in items if item["vertex"] == "V000")
        loaded_axis = next(axis for axis in v000["axes"] if axis["status"] == "loaded")

        self.assertEqual(v000["target_type"], "Point")
        self.assertEqual(loaded_axis["load"]["magnitude"], 10)
        self.assertEqual(loaded_axis["load"]["frequency"], 0)
        self.assertEqual(loaded_axis["load"]["duration"], 1)
        self.assertEqual(loaded_axis["load"]["R"], 0)
        self.assertIn("magnitude: 10", loaded_axis["load_summary"])

    def test_mechanical_bc_items_classify_whole_cube_conditions(self):
        """
        Eight-vertex boundary conditions are represented as one whole-cube target
        """
        data = self._build_valid_upload_object("bc-whole-cube")
        data["mechanical_BC"] = [
            {
                "vertex_list": [
                    "V000",
                    "V100",
                    "V010",
                    "V110",
                    "V001",
                    "V101",
                    "V011",
                    "V111",
                ],
                "constraints": ["loaded", "loaded", "loaded"],
                "loading_type": "force",
                "loading_mode": "static",
                "applied_load": [
                    {
                        "magnitude": [1, 2, 3, 4, 5, 6],
                        "frequency": 0,
                        "duration": 250,
                        "R": 0,
                    }
                ],
            }
        ]

        items = _build_mechanical_bc_items(data)
        whole_cube_items = [item for item in items if item["target_type"] == "Whole cube"]

        self.assertEqual(len(whole_cube_items), 1)
        self.assertEqual(whole_cube_items[0]["vertex"], "Whole cube")
        self.assertEqual(whole_cube_items[0]["vertices"], data["mechanical_BC"][0]["vertex_list"])
        self.assertEqual(whole_cube_items[0]["axes"][0]["load"]["magnitude"], [1, 2, 3, 4, 5, 6])

    def test_mechanical_bc_items_do_not_classify_duplicate_vertices_as_whole_cube(self):
        """
        Whole cube conditions require the full standard vertex set
        """
        data = self._build_valid_upload_object("bc-duplicate-vertices")
        data["mechanical_BC"] = [
            {
                "vertex_list": [
                    "V000",
                    "V100",
                    "V010",
                    "V110",
                    "V001",
                    "V101",
                    "V011",
                    "V011",
                ],
                "constraints": ["loaded", "loaded", "loaded"],
                "applied_load": [{"magnitude": 1}],
            }
        ]

        items = _build_mechanical_bc_items(data)
        defined_items = [item for item in items if item.get("is_defined") is not False]

        self.assertEqual(len(defined_items), 1)
        self.assertNotEqual(defined_items[0]["target_type"], "Whole cube")

    def test_detail_cube_uses_refined_visual_markers(self):
        """
        Detail cube uses a Three.js viewer with solid 3D markers
        """
        template = Path("templates/pages/data_detail.html").read_text(encoding="utf-8")
        viewer_path = Path("static/assets/js/mechanical-bc-viewer.js")

        self.assertTrue(viewer_path.exists())
        viewer = viewer_path.read_text(encoding="utf-8")

        self.assertIn('{% load static %}', template)
        self.assertIn('type="module" src="{% static "assets/js/mechanical-bc-viewer.js" %}"', template)
        self.assertNotIn("cdn.plot.ly", template)
        self.assertNotIn("Plotly.react", template)
        self.assertIn("import * as THREE", viewer)
        self.assertIn("OrbitControls", viewer)
        self.assertIn("new THREE.WebGLRenderer", viewer)
        self.assertIn("new THREE.ConeGeometry", viewer)
        self.assertIn("new THREE.CylinderGeometry", viewer)
        self.assertIn("function getLoadDirectionSigns", viewer)
        self.assertIn("return [-1, 1];", viewer)
        self.assertIn("function drawFaceCondition", viewer)
        self.assertIn("function drawWholeCubeCondition", viewer)
        self.assertIn("createClampMarker", viewer)
        self.assertIn('data-bc-reset', template)
        self.assertIn("function frameScene", viewer)
        self.assertIn("function resetCameraView", viewer)
        self.assertIn("function renderSceneOnce", viewer)
        self.assertIn("new ResizeObserver", viewer)
        self.assertIn("function createCubeWireBox", viewer)
        self.assertIn("function drawGlassCubeEdges", viewer)
        self.assertIn("cubeEdgeHalo", viewer)
        self.assertIn("cubeEdgeLine", viewer)
        self.assertIn('color: "#93c5fd"', viewer)
        self.assertIn("opacity: 0.42", viewer)
        self.assertIn('color: "#7c9fca"', viewer)
        self.assertIn("opacity: 0.96", viewer)
        self.assertIn("new THREE.LineSegments", viewer)
        self.assertIn("new THREE.EdgesGeometry", viewer)
        self.assertIn("cubeSheen", viewer)
        self.assertIn("new THREE.BoxGeometry(1.018, 1.018, 1.018)", viewer)
        self.assertNotIn("cubeEdgeGlow", viewer)
        self.assertNotIn("cubeEdgeCore", viewer)
        self.assertNotIn("makeCylinderBetween(start, end, 0.019", viewer)
        self.assertIn("controls.addEventListener(\"change\", renderSceneOnce);", viewer)
        self.assertIn("renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));", viewer)
        self.assertIn("controls.enableDamping = false;", viewer)
        self.assertNotIn("RoomEnvironment", viewer)
        self.assertNotIn("new THREE.PMREMGenerator", viewer)
        self.assertNotIn("window.requestAnimationFrame(animate)", viewer)
        self.assertNotIn("transmission: 0.48", viewer)
        self.assertNotIn("clearcoat: 1", viewer)
        self.assertNotIn("Single vertex", viewer)
        self.assertIn("camera.up.set(0, 0, 1);", viewer)
        self.assertIn("new THREE.Vector3(1.45, -1.45, 1.15).normalize()", viewer)
        self.assertLess(
            viewer.index("camera.up.set(0, 0, 1);"),
            viewer.index("new OrbitControls(camera"),
        )

    def test_detail_plot_axis_titles_are_placed_beside_axes(self):
        """
        Plot axis titles use matching distance from tick labels
        """
        template = Path("templates/pages/data_detail.html").read_text(encoding="utf-8")

        self.assertIn("function drawAxisTitle", template)
        self.assertIn("function drawXAxisTitle", template)
        self.assertIn("function drawYAxisTitle", template)
        self.assertIn("function formatPlotLabelHtml", template)
        self.assertIn("function getAxisTitlePrefix", template)
        self.assertIn("drawXAxisTitle(ctx, xScale.options.title.text", template)
        self.assertIn("drawYAxisTitle(ctx, yScale.options.title.text", template)
        self.assertIn("plotCustomLegendText.innerHTML", template)
        self.assertIn('return "Stress";', template)
        self.assertIn('return "Strain";', template)
        self.assertIn("const prefixedLabel = prefix ? `${prefix}, ${label}` : label;", template)
        self.assertIn("const xTickLabelOffset = 20;", template)
        self.assertIn("const yTickLabelOffset = 14;", template)
        self.assertIn("const tickLabelFontSize = 12;", template)
        self.assertIn("const xAxisTitleTickGap = 16;", template)
        self.assertIn("const yAxisTitleTickGap = 14;", template)
        self.assertIn("function measureTickLabelWidth", template)
        self.assertIn("function measureWidestTickLabel", template)
        self.assertIn(
            "const titleY = axisY + xTickLabelOffset + tickLabelFontSize + xAxisTitleTickGap;",
            template,
        )
        self.assertIn("const yTickLabelWidth = measureWidestTickLabel(ctx, yScale);", template)
        self.assertIn(
            "const titleX = axisX - yTickLabelOffset - yTickLabelWidth - yAxisTitleTickGap;",
            template,
        )
        self.assertIn("const titleY = (chartArea.top + chartArea.bottom) / 2;", template)
        self.assertIn("ctx.translate(titleX, titleY);", template)
        self.assertIn("ctx.rotate(-Math.PI / 2);", template)
        self.assertIn('drawAxisTitle(ctx, text, 0, 0, "center");', template)
        self.assertIn("drawYAxisTitle(ctx, yScale.options.title.text, chartArea, axisX, yScale);", template)
        self.assertIn("const isCompactPlot = canvas.clientWidth < 640;", template)
        self.assertIn("left: isCompactPlot ? 164 : 190,", template)
        self.assertIn("top: 24,", template)
        self.assertIn("padding: 0 12px;", template)
        self.assertIn("font-style: normal;", template)
        self.assertIn('ctx.font = "400 15px sans-serif";', template)
        self.assertIn('ctx.font = "400 10px sans-serif";', template)
        self.assertNotIn("const titleX = axisX - 88;", template)
        self.assertNotIn("const titleY = axisY + 54;", template)
        self.assertNotIn("const axisTitleTickGap = 34;", template)
        self.assertNotIn("const axisTitleTickGap = 18;", template)
        self.assertNotIn("const axisTitleTickGap = 8;", template)
        self.assertNotIn('ctx.font = "italic 400 15px sans-serif";', template)
        self.assertNotIn('ctx.font = "italic 400 10px sans-serif";', template)
        self.assertNotIn("const titleY = axisY + xTickLabelOffset + tickLabelFontSize + axisTitleTickGap;", template)
        self.assertNotIn("const titleX = axisX - yTickLabelOffset - axisTitleTickGap;", template)
        self.assertNotIn("const titleY = chartArea.top + 16;", template)
        self.assertNotIn("`X, ${xScale.options.title.text}`", template)
        self.assertNotIn("`Y, ${yScale.options.title.text}`", template)
        self.assertNotIn("plotCustomLegendText.textContent =", template)
        self.assertNotIn("chartArea.right + 14, axisY - 1", template)
        self.assertNotIn("axisX - 46, chartArea.top - 26", template)
        self.assertNotIn("left: isCompactPlot ? 206 : 236,", template)

    def test_detail_rows_keep_flat_metadata_fields_separate(self):
        """
        Flat schema fields such as creator_ORCID stay as top-level fields
        """
        rows = _build_detail_rows(
            {
                "creator": ["Jun, Xue"],
                "creator_ORCID": ["0000-0002-1451-2715"],
                "creator_affiliation": ["Ruhr University Bochum"],
                "software": "Abaqus CAE",
                "software_version": "6.14",
            }
        )
        grouped_rows = _group_detail_rows(rows)
        labels = [row["label"] for row in grouped_rows]

        self.assertIn("creator", labels)
        self.assertIn("creator_ORCID", labels)
        self.assertIn("creator_affiliation", labels)
        self.assertIn("software", labels)
        self.assertIn("software_version", labels)
        self.assertFalse(any(row["type"] == "group" and row["label"] == "creator" for row in grouped_rows))

    def test_detail_rows_include_empty_boolean_and_raw_json_values(self):
        """
        Detail rows keep display placeholders for non-text metadata values
        """
        rows = _build_detail_rows(
            {
                "RVE_continuity": True,
                "empty_note": "",
                "missing_value": None,
                "mixed_array": [1, "two"],
                "empty_array": [],
            }
        )
        by_label = {row["label"]: row for row in rows}

        self.assertEqual(by_label["RVE_continuity"]["type"], "boolean")
        self.assertEqual(by_label["RVE_continuity"]["value"], "true")
        self.assertEqual(by_label["empty_note"]["type"], "empty")
        self.assertEqual(by_label["missing_value"]["type"], "empty")
        self.assertEqual(by_label["mixed_array"]["type"], "json")
        self.assertEqual(by_label["empty_array"]["type"], "json")

    def test_detail_rows_add_empty_required_field_placeholders(self):
        """
        Detail rows include required top-level fields even when old data misses them
        """
        rows = _ensure_required_detail_rows(
            {"identifier": "minimal-object", "phase": "Copper"},
            _build_detail_rows({"identifier": "minimal-object", "phase": "Copper"}),
        )
        by_label = {row["label"]: row for row in rows}

        self.assertEqual(by_label["identifier"]["value"], "minimal-object")
        self.assertEqual(by_label["title"]["type"], "empty")
        self.assertEqual(by_label["creator"]["type"], "empty")
        self.assertEqual(by_label["RVE_continuity"]["type"], "empty")

    def test_detail_rows_show_short_numeric_arrays_inline(self):
        """
        Short numeric arrays display inline while longer arrays stay collapsed
        """
        rows = _build_detail_rows(
            {
                "RVE_size": [1, 1, 1],
                "stress_values": [0, 1, 2, 3, 4, 5, 6],
            }
        )
        by_label = {row["label"]: row for row in rows}

        self.assertEqual(by_label["RVE_size"]["type"], "numeric_array")
        self.assertTrue(by_label["RVE_size"].get("is_inline"))
        self.assertEqual(by_label["RVE_size"]["value"], [1, 1, 1])
        self.assertFalse(by_label["stress_values"].get("is_inline"))
        self.assertEqual(by_label["stress_values"]["count"], 7)

    def test_detail_rows_hide_fields_already_shown_as_visualizations(self):
        """
        Detail rows omit mechanical and tensor groups already shown visually
        """
        rows = _filter_visualized_detail_rows(
            _build_detail_rows(
                {
                    "title": "Visualized object",
                    "mechanical_BC": [{"vertex_list": ["V000"]}],
                    "stress": {"stress_11": [0, 1]},
                    "total_strain": {"strain_11": [0, 0.1]},
                    "plastic_strain": {"plastic_strain_11": [0, 0.01]},
                    "phase": [{"phase_identifier": "Copper"}],
                }
            )
        )
        labels = {row["label"] for row in rows}

        self.assertIn("title", labels)
        self.assertIn("phase / phase_identifier", labels)
        self.assertFalse(any(label.startswith("mechanical_BC") for label in labels))
        self.assertFalse(any(label.startswith("stress") for label in labels))
        self.assertFalse(any(label.startswith("total_strain") for label in labels))
        self.assertFalse(any(label.startswith("plastic_strain") for label in labels))

    def test_extract_plot_variables_adds_equivalent_mechanical_values(self):
        """
        Plot variables include calculated equivalent stress and strain values
        """
        data = {
            "stress": {
                "stress_11": [0, 1],
                "stress_22": [0, 0],
                "stress_33": [0, 0],
                "stress_12": [0, 0],
                "stress_13": [0, 0],
                "stress_23": [0, 0],
            },
            "total_strain": {
                "strain_11": [0, 1],
                "strain_22": [0, -0.5],
                "strain_33": [0, -0.5],
                "strain_12": [0, 0],
                "strain_13": [0, 0],
                "strain_23": [0, 0],
            },
            "plastic_strain": {
                "plastic_strain_11": [0, 1],
                "plastic_strain_22": [0, -0.5],
                "plastic_strain_33": [0, -0.5],
                "plastic_strain_12": [0, 0],
                "plastic_strain_13": [0, 0],
                "plastic_strain_23": [0, 0],
            },
            "units": {"Stress": "MPa", "Strain": 1},
        }

        variables = _extract_plot_variables(data, units=data["units"])
        by_key = {variable["key"]: variable for variable in variables}

        self.assertEqual(by_key["stress.equivalent_stress"]["values"], [0, 1])
        self.assertEqual(by_key["total_strain.equivalent_total_strain"]["values"], [0, 1])
        self.assertEqual(by_key["plastic_strain.equivalent_plastic_strain"]["values"], [0, 1])
        self.assertEqual(by_key["stress.equivalent_stress"]["symbol_label"], "sigma_eq")
        self.assertEqual(by_key["stress.equivalent_stress"]["display_label"], "\u03c3_eq")
        self.assertEqual(by_key["total_strain.equivalent_total_strain"]["display_label"], "\u03b5_eq")
        self.assertEqual(
            by_key["plastic_strain.equivalent_plastic_strain"]["display_label"],
            "\u03b5_p,eq",
        )
        self.assertNotIn("Equivalent", by_key["stress.equivalent_stress"]["display_label"])
        self.assertNotIn("Equivalent", by_key["total_strain.equivalent_total_strain"]["display_label"])
        self.assertEqual(by_key["total_strain.equivalent_total_strain"]["kind"], "strain")
        self.assertEqual(by_key["total_strain.strain_11"]["unit"], "")
        self.assertEqual(by_key["total_strain.equivalent_total_strain"]["unit"], "")

    def test_public_home_page_is_available_without_login(self):
        """
        The root page shows a landing page without exposing dataset records
        """
        JSONData.objects.create(
            owner=self.owner,
            data={
                "identifier": "public-copper",
                "title": "Public copper simulation",
                "phase": [{"phase_identifier": "Copper"}],
                "software": "Abaqus CAE",
            },
            access_type="all",
        )

        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Public copper simulation")
        self.assertNotContains(response, "public-copper")
        self.assertNotContains(response, "Showing latest")
        self.assertNotContains(response, "demo")
        self.assertContains(response, "The material record behind every simulation")
        self.assertContains(response, 'class="microstructure-map"')
        self.assertContains(response, "Polycrystal map")
        self.assertContains(response, "--atlas-canvas: #f4f7fa;")
        self.assertContains(response, "--atlas-navy: #3f4d67;")
        self.assertContains(response, "--atlas-blue: #04a9f5;")
        self.assertContains(response, "--atlas-blue-ink: #0078b3;")
        self.assertNotContains(response, 'class="material-fingerprint"')
        self.assertContains(response, "Search data")
        self.assertContains(response, "Upload JSON")
        self.assertContains(response, "Materials Atlas")
        self.assertContains(response, "Example materials index")
        self.assertContains(response, "rve-copper-001")
        self.assertContains(response, "Synthetic example")
        self.assertContains(response, "Sign in to inspect dataset records")
        self.assertContains(response, "Create account")
        self.assertContains(response, "prefers-reduced-motion: reduce")
        self.assertContains(response, ":focus-visible")
        self.assertContains(response, "<title>Materials Data Platform</title>", html=True)
        self.assertNotContains(response, "Datta able")
        self.assertNotContains(response, "data-console")
        self.assertNotContains(response, "data-slab")
        self.assertContains(response, "footer-bottom")
        self.assertContains(response, "© 2026 Materials Simulation Data Platform")
        self.assertContains(response, "Django UI")
        self.assertContains(response, "JSON validation")

    def test_login_page_uses_platform_branding(self):
        """
        Login page uses platform branding instead of template branding
        """
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Materials Simulation Data Platform")
        self.assertNotContains(response, "logo-dark.svg")

    def test_register_page_uses_platform_branding(self):
        """
        Register page uses platform branding instead of template branding
        """
        response = self.client.get(reverse("register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Materials Simulation Data Platform")
        self.assertNotContains(response, "logo-dark.svg")
