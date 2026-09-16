from urllib.parse import urlencode

from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .middleware import requires_orcid_account_setup
from .models import AccountProfile, JSONData
from .orcid_auth import complete_orcid_login
from .test_orcid_auth import ORCIDCallbackTestMixin


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ORCIDOnboardingGateTests(TestCase):
    """
    Require initial credentials before an ORCID account can use the application
    """

    def setUp(self):
        """
        Create an existing ORCID account with an unfinished login setup
        """
        self.user = User.objects.create_user(username="orcid_0000000214512715")
        self.profile = AccountProfile.objects.create(
            user=self.user,
            authenticated_orcid="0000-0002-1451-2715",
            orcid_authenticated_at=timezone.now(),
        )
        self.data = JSONData.objects.create(
            owner=self.user, data={"identifier": "onboarding-gate"}
        )
        self.client.force_login(self.user)

    def test_existing_session_cannot_browse_protected_pages(self):
        """
        Catch bypasses through direct requests using a previously created session
        """
        for target in (
            "/search/?keyword=alloys",
            "/data-list/",
            "/upload/",
            "/settings/",
            "/password/change/",
            f"/data-list/{self.data.pk}/",
        ):
            with self.subTest(target=target):
                response = self.client.get(target)
                expected = "/settings/orcid/setup/?" + urlencode({"next": target})
                self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_pending_posts_cannot_mutate_or_replay_after_setup(self):
        """
        Block direct management submissions and discard their return targets
        """
        for target in (
            "/settings/orcid/disconnect/",
            "/settings/",
            "/password/change/",
            f"/data-list/{self.data.pk}/delete/",
        ):
            with self.subTest(target=target):
                response = self.client.post(
                    target,
                    {"orcid": self.profile.authenticated_orcid, "username": "bypassed"},
                )
                self.assertRedirects(
                    response,
                    "/settings/orcid/setup/?next=%2Fsearch%2F",
                    fetch_redirect_response=False,
                )
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.username, "orcid_0000000214512715")
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.profile.authenticated_orcid, "0000-0002-1451-2715")
        self.assertTrue(JSONData.objects.filter(pk=self.data.pk).exists())

    def test_authentication_urls_never_become_onboarding_return_targets(self):
        """
        Avoid retaining callback credentials or reentering authentication flows
        """
        for target in (
            "/settings/orcid/callback/?code=private-code&state=private-state",
            "/login/orcid/?next=%2Fupload%2F",
            "/settings/orcid/connect/?next=%2Fupload%2F",
            "/login/?next=%2Fsearch%2F&username=private-name",
            "/accounts/login/?next=%2Fsearch%2F",
            "/admin/login/?next=%2Fadmin%2F",
            "/register/",
        ):
            with self.subTest(target=target):
                response = self.client.get(target)
                self.assertRedirects(
                    response,
                    "/settings/orcid/setup/?next=%2Fsearch%2F",
                    fetch_redirect_response=False,
                )

    def test_sensitive_query_values_on_an_app_url_are_not_retained(self):
        """
        Avoid copying authentication parameters even onto an ordinary app route
        """
        response = self.client.get("/search/?code=private-code&state=private-state")

        self.assertRedirects(
            response,
            "/settings/orcid/setup/?next=%2Fsearch%2F",
            fetch_redirect_response=False,
        )

    def test_setup_submission_is_allowed_through_the_gate(self):
        """
        Allow the initial credential form to return its own validation errors
        """
        response = self.client.post(
            reverse("orcid_setup_credentials"),
            {"orcid": self.profile.authenticated_orcid},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.get(pk=self.user.pk).has_usable_password())

    def test_logout_remains_available_at_all_real_logout_routes(self):
        """
        Keep users able to leave unfinished setup without completing credentials
        """
        for target in ("/logout/", "/accounts/logout/", "/admin/logout/"):
            with self.subTest(target=target):
                if target == "/admin/logout/":
                    self.user.is_staff = True
                    self.user.save(update_fields=["is_staff"])
                self.client.force_login(self.user)
                response = self.client.post(target)
                self.assertNotIn(SESSION_KEY, self.client.session)
                self.assertNotEqual(
                    response.headers.get("Location"),
                    "/settings/orcid/setup/?next=%2Fsearch%2F",
                )

    def test_csrf_is_enforced_before_redirecting_pending_submissions(self):
        """
        Reject unsafe submissions before allowing any onboarding redirect
        """
        protected_client = Client(enforce_csrf_checks=True)
        protected_client.force_login(self.user)

        response = protected_client.post("/settings/orcid/disconnect/")

        self.assertEqual(response.status_code, 403)

    def test_completed_orcid_account_bypasses_setup(self):
        """
        Unlock ordinary access after the account has usable local credentials
        """
        self.user.username = "chosen-researcher"
        self.user.set_password("Quartz!Mosaic72River")
        self.user.save(update_fields=["username", "password"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("search"))

        self.assertEqual(response.status_code, 200)

    def test_ordinary_local_account_without_an_orcid_profile_is_unchanged(self):
        """
        Do not redirect accounts that never entered ORCID onboarding
        """
        local_user = User.objects.create_user(username="ordinary-local", password="pass")
        self.client.force_login(local_user)

        response = self.client.get(reverse("search"))

        self.assertEqual(response.status_code, 200)

    def test_unverified_legacy_orcid_claim_does_not_trigger_setup(self):
        """
        Require an authenticated identity rather than editable legacy profile text
        """
        self.profile.orcid = self.profile.authenticated_orcid
        self.profile.authenticated_orcid = None
        self.profile.save(update_fields=["orcid", "authenticated_orcid"])

        response = self.client.get(reverse("search"))

        self.assertEqual(response.status_code, 200)

    def test_anonymous_login_page_remains_available(self):
        """
        Keep anonymous authentication outside the mandatory account setup gate
        """
        self.client.logout()

        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)

    def test_inactive_and_anonymous_users_need_no_profile_query(self):
        """
        Exclude unauthenticated or disabled accounts before reading profiles
        """
        self.user.is_active = False

        with self.assertNumQueries(0):
            self.assertFalse(requires_orcid_account_setup(AnonymousUser()))
            self.assertFalse(requires_orcid_account_setup(self.user))

    def test_usable_password_accounts_need_no_profile_query(self):
        """
        Keep the normal application path free of added profile queries
        """
        self.user.set_password("Quartz!Mosaic72River")

        with self.assertNumQueries(0):
            self.assertFalse(requires_orcid_account_setup(self.user))


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    ORCID_CLIENT_ID="APP-TEST",
    ORCID_CLIENT_SECRET="test-secret",
)
class ORCIDOnboardingLoginTests(ORCIDCallbackTestMixin, TestCase):
    """
    Send unfinished ORCID logins directly to the mandatory setup page
    """

    def test_first_orcid_login_opens_setup_with_the_original_safe_target(self):
        """
        Prevent newly created ORCID users from landing inside the application
        """
        response = self._complete_login(next_url="/search/?keyword=alloys")

        self.assertEqual(
            response["Location"],
            "/settings/orcid/setup/?next=%2Fsearch%2F%3Fkeyword%3Dalloys",
        )
        self.assertFalse(User.objects.get().has_usable_password())
        self.assertIn(SESSION_KEY, self.client.session)

    def test_existing_unfinished_orcid_account_opens_setup_again(self):
        """
        Apply the same requirement to accounts created before mandatory setup
        """
        user = User.objects.create_user(username="existing-orcid-account")
        AccountProfile.objects.create(user=user, authenticated_orcid=self.primary_orcid)

        response = self._complete_login()

        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fsearch%2F")
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        self.assertEqual(User.objects.count(), 1)

    def test_already_authenticated_identity_is_still_sent_to_setup(self):
        """
        Prevent the callback helper's existing session branch from bypassing setup
        """
        user = User.objects.create_user(username="already-signed-in")
        AccountProfile.objects.create(user=user, authenticated_orcid=self.primary_orcid)
        request = RequestFactory().get("/settings/orcid/callback/")
        SessionMiddleware(lambda current_request: None).process_request(request)
        MessageMiddleware(lambda current_request: None).process_request(request)
        request.user = user

        response = complete_orcid_login(request, self.primary_orcid, "/upload/")

        self.assertEqual(response["Location"], "/settings/orcid/setup/?next=%2Fupload%2F")

    def test_completed_account_logs_in_directly_to_its_target(self):
        """
        Bypass initial setup after the same account acquires local credentials
        """
        user = User.objects.create_user(username="chosen-name", password="local-password")
        AccountProfile.objects.create(user=user, authenticated_orcid=self.primary_orcid)

        response = self._complete_login(next_url="/upload/")

        self.assertEqual(response["Location"], "/upload/")
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
