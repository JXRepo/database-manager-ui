from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse


class UploadNavigationTests(TestCase):
    """
    Limit embedded upload navigation to authenticated application pages
    """

    def setUp(self):
        """
        Create an ordinary account with an authenticated test session
        """
        self.owner = User.objects.create_user(username="navigation-owner", password="test-only-password")
        self.client.force_login(self.owner)

    def test_application_pages_allow_only_same_origin_frames(self):
        """
        Allow complete application pages to keep their script lifecycle in a frame
        """
        for name in ("search", "json_data_list", "upload_json", "charts", "notification_list", "getting_started"):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")

    def test_authentication_and_anonymous_pages_keep_deny(self):
        """
        Retain frame denial on credential flows and unauthenticated responses
        """
        for name in ("login", "register", "password_change"):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.client.logout()
        response = self.client.get(reverse("search"))
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_api_and_failed_responses_do_not_gain_frame_permission(self):
        """
        Do not widen the embedding policy for JSON or failed page responses
        """
        from .upload_navigation import UploadNavigationMiddleware

        request = RequestFactory().get(reverse("search"))
        request.user = self.owner
        request.resolver_match = resolve(request.path)
        middleware = UploadNavigationMiddleware(lambda request: HttpResponse())
        for response in (HttpResponse(status=403), HttpResponse("{}", content_type="application/json")):
            self.assertNotIn("X-Frame-Options", middleware.process_response(request, response))
