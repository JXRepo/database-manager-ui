import json
from unittest.mock import Mock, patch

import requests
from django.contrib.auth.models import User
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AccountProfile
from .test_orcid_auth import ORCIDCallbackTestMixin


@override_settings(
    ORCID_BASE_URL="https://sandbox.orcid.org",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ORCIDProfileTests(ORCIDCallbackTestMixin, TestCase):
    """
    Exercise optional public profile imports through the real OAuth callback
    """

    def setUp(self):
        """
        Supply synthetic API responses at the HTTP boundary
        """
        super().setUp()
        self.email = "researcher@example.com"
        self.response_status = 200
        self.responses = {
            "person": {"emails": {"email": [self._email(self.email, primary=True)]}},
            "employments": self._employments(self._employment("Materials Institute")),
        }
        self.profile_request.side_effect = self._respond

    def test_public_research_profile_is_imported_on_login(self):
        """
        Fill the five optional research fields from public ORCID sections
        """
        self.responses["person"].update({
            "name": {
                "visibility": "public",
                "given-names": {"value": "Ada"},
                "family-name": {"value": "Lovelace"},
                "credit-name": {"value": "A. Lovelace"},
            },
            "researcher-urls": {"researcher-url": [{
                "visibility": "public",
                "url": {"value": "https://example.com/research"},
                "display-index": 1,
            }]},
            "keywords": {"keyword": [
                {"visibility": "public", "content": "Materials simulation"},
                {"visibility": "public", "content": "Crystal plasticity"},
            ]},
        })
        self.responses["employments"] = self._employments(self._employment(
            "Materials Institute",
            **{"department-name": "Mechanics", "role-title": "Researcher"},
        ))
        self._complete_login()
        profile = AccountProfile.objects.get(authenticated_orcid=self.primary_orcid)
        for field, expected in {
            "display_name": "A. Lovelace",
            "department": "Mechanics",
            "position": "Researcher",
            "website": "https://example.com/research",
            "research_keywords": "Materials simulation, Crystal plasticity",
        }.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(profile, field, ""), expected)

    def test_public_name_fallback_respects_visibility_and_length(self):
        """
        Use given and family names only when the public name can be stored
        """
        profile = self._existing_account()
        for name, expected in [
            ({"visibility": "public", "credit-name": None,
              "given-names": {"value": " Ada "}, "family-name": {"value": " Lovelace "}},
             "Ada Lovelace"),
            ({"visibility": "PUBLIC", "given-names": {"value": "Ada"}}, "Ada"),
            ({"visibility": "private", "credit-name": {"value": "Private Name"}}, ""),
            ({"credit-name": {"value": "Unmarked Name"}}, ""),
            ({"visibility": "public", "credit-name": {"value": "x" * 256}}, ""),
            ({"visibility": "public", "given-names": {"value": []},
              "family-name": "invalid"}, ""),
        ]:
            with self.subTest(name=name):
                self.client.logout()
                AccountProfile.objects.filter(pk=profile.pk).update(display_name="")
                self.responses["person"] = {"name": name}
                self._complete_login()
                profile.refresh_from_db()
                self.assertEqual(profile.display_name, expected)

    def test_website_and_keywords_use_valid_public_items_in_preferred_order(self):
        """
        Skip private or unsafe URLs and deduplicate public research keywords
        """
        profile = self._existing_account()
        self.responses["person"] = {
            "researcher-urls": {"researcher-url": [
                {"visibility": "private", "display-index": 99,
                 "url": {"value": "https://example.com/private"}},
                {"visibility": "public", "display-index": 90,
                 "url": {"value": "javascript:alert(1)"}},
                {"visibility": "public", "display-index": 80,
                 "url": {"value": "ftp://example.com/files"}},
                {"visibility": "public", "display-index": 70,
                 "url": {"value": "https://example.com/" + "x" * 500}},
                {"visibility": "public", "display-index": 1,
                 "url": {"value": "https://example.com/secondary"}},
                {"visibility": "PUBLIC", "display-index": "5",
                 "url": {"value": "https://example.com/preferred"}},
            ]},
            "keywords": {"keyword": [
                {"visibility": "private", "content": "Private keyword", "display-index": 9},
                {"visibility": "limited", "content": "Limited keyword", "display-index": 8},
                {"visibility": "public", "content": " Plasticity ", "display-index": 1},
                {"visibility": "PUBLIC", "content": "  Materials   simulation ", "display-index": 3},
                {"visibility": "public", "content": "materials simulation", "display-index": 2},
                {"visibility": "public", "content": {"invalid": "shape"}},
                {"visibility": "public", "content": "\x00bad"},
                {"visibility": "public", "content": " "},
            ]},
        }
        self._complete_login()
        profile.refresh_from_db()
        self.assertEqual(profile.website, "https://example.com/preferred")
        self.assertEqual(profile.research_keywords, "Materials simulation, Plasticity")

    def test_malformed_person_sections_and_overlong_keywords_remain_empty(self):
        """
        Keep optional details empty when provider values cannot be used safely
        """
        profile = self._existing_account()
        for person in [
            {"name": [], "researcher-urls": [], "keywords": None, "emails": []},
            {"researcher-urls": {"researcher-url": "invalid"},
             "keywords": {"keyword": "invalid"}},
            {"researcher-urls": {"researcher-url": [None, {"visibility": "public", "url": []}]},
             "keywords": {"keyword": [None, {"content": "Missing visibility"}]}},
            {"keywords": {"keyword": [
                {"visibility": "public", "content": "A" * 600},
                {"visibility": "public", "content": "B" * 600},
            ]}},
        ]:
            with self.subTest(person=person):
                self.client.logout()
                self.responses["person"] = person
                response = self._complete_login()
                profile.refresh_from_db()
                self.assertEqual(response["Location"], "/search/")
                self.assertEqual(profile.display_name, "")
                self.assertEqual(profile.website, "")
                self.assertEqual(profile.research_keywords, "")

    def test_affiliation_fields_do_not_mix_institutions_or_roles(self):
        """
        Keep departments and positions attached to the selected current employment
        """
        profile = self._existing_account()
        materials = self._employment(
            "Materials Institute", **{"department-name": "Mechanics", "role-title": "Researcher"}
        )
        other = self._employment(
            "Other Institute", **{"department-name": "Chemistry", "role-title": "Professor"}
        )
        second_role = self._employment(
            "Materials Institute", **{"department-name": "Physics", "role-title": "Lecturer"}
        )
        for institution, department, position, items, expected in [
            ("", "", "", [materials, other], ("", "", "")),
            (" Other Institute ", "", "", [materials, other],
             (" Other Institute ", "Chemistry", "Professor")),
            ("Manual Institute", "", "", [materials], ("Manual Institute", "", "")),
            ("Materials Institute", "Manual department", "", [materials],
             ("Materials Institute", "Manual department", "")),
            ("", "", "", [materials, second_role], ("Materials Institute", "", "")),
            ("Materials Institute", "", "Lecturer", [materials, second_role],
             ("Materials Institute", "Physics", "Lecturer")),
            ("", "", "", [materials, materials], ("Materials Institute", "Mechanics", "Researcher")),
        ]:
            with self.subTest(institution=institution, department=department, position=position):
                self.client.logout()
                AccountProfile.objects.filter(pk=profile.pk).update(
                    institution=institution, department=department, position=position,
                )
                self.responses["employments"] = self._employments(*items)
                self._complete_login()
                profile.refresh_from_db()
                self.assertEqual((profile.institution, profile.department, profile.position), expected)

    def test_roles_cannot_be_combined_from_separate_employment_entries(self):
        """
        Avoid constructing a department and position pair absent from ORCID
        """
        profile = self._existing_account()
        self.responses["employments"] = self._employments(
            self._employment("Materials Institute", **{"department-name": "Mechanics"}),
            self._employment("Materials Institute", **{"role-title": "Professor"}),
        )
        self._complete_login()
        profile.refresh_from_db()
        self.assertEqual(profile.institution, "Materials Institute")
        self.assertEqual(profile.department, "")
        self.assertEqual(profile.position, "")

    def test_concurrent_profile_edits_are_not_overwritten(self):
        """
        Recheck each personal field and the institution after fetching ORCID data
        """
        profile = self._existing_account()
        self.responses["person"].update({
            "name": {"visibility": "public", "credit-name": {"value": "Provider Name"}},
            "researcher-urls": {"researcher-url": [{
                "visibility": "public", "url": {"value": "https://example.com/provider"},
            }]},
            "keywords": {"keyword": [{"visibility": "public", "content": "Provider keyword"}]},
        })
        self.responses["employments"] = self._employments(self._employment(
            "Materials Institute", **{"department-name": "Mechanics", "role-title": "Researcher"}
        ))

        def edit_during_response(url, **kwargs):
            """
            Apply a manual edit while the optional provider request is in flight

            Parameters
            ----------
            url : str
                Requested ORCID endpoint.
            **kwargs : dict
                Original HTTP request options.

            Returns
            -------
            Mock
                Provider response after the independent edit.
            """
            AccountProfile.objects.filter(pk=profile.pk).update(
                display_name="Edited Name", institution="Edited Institute",
                website="https://example.com/edited", research_keywords="Edited keyword",
            )
            return self._respond(url, **kwargs)

        self.profile_request.side_effect = edit_during_response
        self._complete_login()
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Edited Name")
        self.assertEqual(profile.institution, "Edited Institute")
        self.assertEqual(profile.website, "https://example.com/edited")
        self.assertEqual(profile.research_keywords, "Edited keyword")
        self.assertEqual(profile.department, "")
        self.assertEqual(profile.position, "")

    def _email(self, value, **overrides):
        """
        Build one synthetic ORCID email item

        Parameters
        ----------
        value : object
            Email value supplied by the provider.
        **overrides : dict
            Visibility or verification changes for a scenario.

        Returns
        -------
        dict
            Email item in the ORCID response format.
        """
        return {
            "email": value,
            "verified": True,
            "primary": False,
            "visibility": "public",
            **overrides,
        }

    def _employment(self, name, **overrides):
        """
        Build one synthetic public employment summary

        Parameters
        ----------
        name : object
            Organization name supplied by the provider.
        **overrides : dict
            Date or visibility changes for a scenario.

        Returns
        -------
        dict
            Current employment unless overridden.
        """
        return {
            "organization": {"name": name},
            "visibility": "public",
            "start-date": None,
            "end-date": None,
            **overrides,
        }

    def _employments(self, *items):
        """
        Wrap summaries in the API version 3 affiliation groups

        Parameters
        ----------
        *items : dict
            Employment summaries to include.

        Returns
        -------
        dict
            Public employment section.
        """
        summaries = [{"employment-summary": item} for item in items]
        return {"affiliation-group": [{"summaries": summaries}]}

    def _respond(self, url, **kwargs):
        """
        Return a streamed response or a provider failure

        Parameters
        ----------
        url : str
            Requested public API endpoint.
        **kwargs : dict
            HTTP options supplied by the application.

        Returns
        -------
        Mock
            Context manager implementing the HTTP response boundary.
        """
        value = self.responses[url.rsplit("/", 1)[-1]]
        if isinstance(value, Exception):
            raise value
        response = Mock()
        response.status_code = self.response_status
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        response.iter_content.return_value = [body]
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def _existing_account(self, email="", institution=""):
        """
        Create a local account already connected to the verified identity

        Parameters
        ----------
        email : str
            Existing local email.
        institution : str
            Existing local institution.

        Returns
        -------
        AccountProfile
            Connected profile with usable local credentials.
        """
        user = User.objects.create_user("researcher", email=email, password="pass")
        return AccountProfile.objects.create(
            user=user, authenticated_orcid=self.primary_orcid, institution=institution
        )

    def test_first_login_imports_public_details_without_matching_by_email(self):
        """
        Add details to the new identity without taking over a matching account
        """
        other = User.objects.create_user("other", email=self.email, password="pass")
        response = self._complete_login()
        profile = AccountProfile.objects.select_related("user").get(
            authenticated_orcid=self.primary_orcid
        )
        self.assertEqual(profile.user.email, self.email)
        self.assertEqual(profile.institution, "Materials Institute")
        self.assertNotEqual(profile.user_id, other.pk)
        self.assertEqual(int(self.client.session["_auth_user_id"]), profile.user_id)
        self.assertFalse(profile.user.has_usable_password())
        self.assertFalse(profile.user.is_staff)
        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertNotIn(self.access_token, str(dict(self.client.session)))
        for call in self.profile_request.call_args_list:
            self.assertTrue(call.args[0].startswith(
                f"https://pub.sandbox.orcid.org/v3.0/{self.primary_orcid}/"
            ))
            self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {self.access_token}")
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertTrue(call.kwargs["stream"])

    def test_existing_details_are_preserved_without_api_calls(self):
        """
        Keep user edits and avoid requesting profile data when nothing is missing
        """
        profile = self._existing_account("local@example.com", "Local Institute")
        AccountProfile.objects.filter(pk=profile.pk).update(
            display_name="Local Name", department="Local Department", position="Local Role",
            website="https://example.com/local", research_keywords="Local research",
        )
        self._complete_login()
        profile.refresh_from_db()
        self.assertEqual(profile.user.email, "local@example.com")
        self.assertEqual(profile.institution, "Local Institute")
        self.profile_request.assert_not_called()

    def test_partial_profile_fetches_only_the_missing_field(self):
        """
        Fill one empty field without overwriting or requesting the other
        """
        profile = self._existing_account(email="local@example.com")
        AccountProfile.objects.filter(pk=profile.pk).update(
            display_name="Local Name", website="https://example.com/local",
            research_keywords="Local research",
        )
        self._complete_login()
        profile.refresh_from_db()
        self.assertEqual(profile.institution, "Materials Institute")
        self.assertEqual(profile.user.email, "local@example.com")
        self.assertEqual(self.profile_request.call_count, 1)
        self.assertTrue(self.profile_request.call_args.args[0].endswith("/employments"))

    def test_connect_and_reconnect_fill_empty_fields_on_the_same_account(self):
        """
        Import on explicit linking without replacing the local account
        """
        user = User.objects.create_user("local", password="pass")
        self.client.force_login(user)
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                User.objects.filter(pk=user.pk).update(email="")
                AccountProfile.objects.filter(user=user).update(institution="")
                response = self._request_callback(
                    {"code": self.authorization_code}, intent="link", user_id=user.pk
                )
                user.refresh_from_db()
                self.assertEqual(response["Location"], reverse("account_settings"))
                self.assertEqual(user.email, self.email)
                self.assertEqual(user.profile.institution, "Materials Institute")
                self.assertEqual(User.objects.count(), 1)

    def test_rejected_link_does_not_request_or_save_details(self):
        """
        Leave both accounts untouched when the identity belongs to another user
        """
        owner = self._existing_account()
        other = User.objects.create_user("other", password="pass")
        self.client.force_login(other)
        self._request_callback(
            {"code": self.authorization_code}, intent="link", user_id=other.pk
        )
        self.profile_request.assert_not_called()
        other.refresh_from_db()
        owner.refresh_from_db()
        self.assertEqual(other.email, "")
        self.assertEqual(owner.institution, "")

    def test_timeout_keeps_login_and_still_imports_the_other_field(self):
        """
        Treat remote profile reads as optional after authentication succeeds
        """
        profile = self._existing_account()
        self.responses["person"] = requests.Timeout("provider timeout")
        response = self._complete_login(next_url="/upload/")
        profile.refresh_from_db()
        self.assertEqual(response["Location"], "/upload/")
        self.assertEqual(profile.user.email, "")
        self.assertEqual(profile.institution, "Materials Institute")

    def test_only_valid_public_verified_emails_are_imported(self):
        """
        Prefer a valid primary address and ignore private or malformed values
        """
        profile = self._existing_account(institution="Local Institute")
        invalid = [
            self._email("private@example.com", visibility="PRIVATE", primary=True),
            self._email("limited@example.com", visibility="LIMITED"),
            self._email("unchecked@example.com", verified=False),
            self._email("string@example.com", verified="true"),
            self._email("not-an-email"), self._email({}),
            self._email("a" * 255 + "@example.com"),
        ]
        for entries, expected in [
            (invalid, ""),
            (invalid + [self._email("secondary@example.com")], "secondary@example.com"),
            ([self._email("secondary@example.com"), self._email(self.email, primary=True)], self.email),
        ]:
            with self.subTest(expected=expected):
                self.client.logout()
                User.objects.filter(pk=profile.user_id).update(email="")
                self.responses["person"] = {"emails": {"email": entries}}
                self._complete_login()
                self.assertEqual(User.objects.get(pk=profile.user_id).email, expected)

    def test_institution_uses_one_unambiguous_current_employer(self):
        """
        Ignore ended, future, private and ambiguous affiliations
        """
        profile = self._existing_account(email="local@example.com")
        past = self._employment("Past Institute", **{"end-date": {"year": {"value": "2000"}}})
        future = self._employment("Future Institute", **{"start-date": {"year": {"value": "2999"}}})
        private = self._employment("Private Institute", visibility="PRIVATE")
        current = self._employment("Materials Institute")
        for items, expected in [
            ([past, future, private], ""),
            ([past, current, future], "Materials Institute"),
            ([current, current], "Materials Institute"),
            ([current, self._employment("Other Institute")], ""),
            ([self._employment("x" * 256)], ""),
            ([self._employment("Invalid date", **{"end-date": "invalid"})], ""),
        ]:
            with self.subTest(expected=expected, items=items):
                self.client.logout()
                AccountProfile.objects.filter(pk=profile.pk).update(institution="")
                self.responses["employments"] = self._employments(*items)
                self._complete_login()
                profile.refresh_from_db()
                self.assertEqual(profile.institution, expected)

    def test_empty_or_malformed_responses_do_not_block_login(self):
        """
        Reject unusable and oversized provider bodies while retaining sign in
        """
        profile = self._existing_account()
        for body in [None, [], {"email": None, "affiliation-group": "invalid"}, b"not json", b"x" * (512 * 1024 + 1)]:
            with self.subTest(body_type=type(body)):
                self.client.logout()
                self.responses = {"person": body, "employments": body}
                response = self._complete_login()
                self.assertEqual(response["Location"], "/search/")
                profile.refresh_from_db()
                self.assertEqual(profile.user.email, "")
                self.assertEqual(profile.institution, "")

    def test_concurrent_user_edits_and_disconnect_are_respected(self):
        """
        Recheck empty fields and identity binding after the network request
        """
        profile = self._existing_account()
        for disconnect in [False, True]:
            with self.subTest(disconnect=disconnect):
                self.client.logout()
                User.objects.filter(pk=profile.user_id).update(email="")
                AccountProfile.objects.filter(pk=profile.pk).update(
                    institution="", authenticated_orcid=self.primary_orcid
                )
                with patch.object(self, "_respond", wraps=self._respond) as respond:
                    def concurrent_response(url, **kwargs):
                        """
                        Simulate a separate update before the HTTP response arrives
                        """
                        if disconnect:
                            AccountProfile.objects.filter(pk=profile.pk).update(authenticated_orcid=None)
                        else:
                            User.objects.filter(pk=profile.user_id).update(email="edited@example.com")
                            AccountProfile.objects.filter(pk=profile.pk).update(institution="Edited Institute")
                        return respond(url, **kwargs)

                    self.profile_request.side_effect = concurrent_response
                    self._complete_login()
                profile.refresh_from_db()
                self.assertEqual(profile.user.email, "" if disconnect else "edited@example.com")
                self.assertEqual(profile.institution, "" if disconnect else "Edited Institute")

    def test_http_errors_and_redirects_keep_login_without_importing(self):
        """
        Keep login usable on denied, rate limited or redirected profile requests
        """
        profile = self._existing_account()
        for status in [302, 401, 403, 404, 429, 503]:
            with self.subTest(status=status):
                self.client.logout()
                self.response_status = status
                response = self._complete_login()
                profile.refresh_from_db()
                self.assertEqual(response["Location"], "/search/")
                self.assertEqual(profile.user.email, "")
                self.assertEqual(profile.institution, "")

    def test_profile_save_failure_preserves_the_authenticated_session(self):
        """
        Roll back optional profile updates without undoing a successful login
        """
        profile = self._existing_account()
        with patch.object(AccountProfile, "save", side_effect=OperationalError("unavailable")):
            with self.assertLogs("apps.pages.orcid_profile", level="WARNING") as logs:
                response = self._complete_login()
        self.assertEqual(response["Location"], "/search/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), profile.user_id)
        profile.refresh_from_db()
        self.assertEqual(profile.user.email, "")
        self.assertEqual(profile.institution, "")
        self.assertNotIn(self.access_token, str(logs.output))

    @override_settings(ORCID_BASE_URL="https://orcid.org")
    def test_production_login_uses_the_production_public_api(self):
        """
        Keep production tokens on the matching production API host
        """
        self._complete_login()
        self.assertEqual(self.profile_request.call_count, 2)
        for call in self.profile_request.call_args_list:
            self.assertTrue(call.args[0].startswith("https://pub.orcid.org/v3.0/"))

    @override_settings(ORCID_BASE_URL="https://unexpected.example")
    def test_unknown_provider_host_does_not_receive_profile_tokens(self):
        """
        Skip optional imports when the configured host has no known API mapping
        """
        self._complete_login()
        self.profile_request.assert_not_called()

    def test_imported_details_remain_escaped_and_editable_in_settings(self):
        """
        Display provider text safely and preserve the user's subsequent edits
        """
        profile = self._existing_account()
        self.responses["employments"] = self._employments(
            self._employment("Institute <Research>")
        )
        self._complete_login()
        response = self.client.get(reverse("account_settings"))
        self.assertContains(response, self.email)
        self.assertContains(response, "Institute &lt;Research&gt;")
        self.assertNotContains(response, "Institute <Research>")
        self.assertContains(response, "You can complete or edit them above.")
        self.client.post(reverse("account_settings"), {
            "username": "researcher",
            "email": "chosen@example.com",
            "institution": "Chosen Institute",
        })
        self.client.logout()
        self._complete_login()
        profile.refresh_from_db()
        self.assertEqual(profile.user.email, "chosen@example.com")
        self.assertEqual(profile.institution, "Chosen Institute")
