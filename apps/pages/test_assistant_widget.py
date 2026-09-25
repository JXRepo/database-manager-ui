import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import JSONData


class AssistantWidgetTests(TestCase):
    """
    Check global assistant availability and page context
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create an owner and a private detail page
        """
        cls.owner = User.objects.create_user(username="widget-owner")
        cls.obj = JSONData.objects.create(
            owner=cls.owner, data={"identifier": "widget-data"}, access_type="c",
        )

    def test_signed_in_pages_have_one_assistant(self):
        """
        Keep the assistant available across application layouts
        """
        self.client.force_login(self.owner)
        for name in (
            "search", "upload_json", "json_data_list", "share",
            "shared_with_me", "sharing_history", "notification_list",
            "account_settings", "password_change", "password_change_done",
            "getting_started",
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(name), follow=True)
                self.assertContains(response, 'class="fair-assistant-widget"', count=1)
                self.assertContains(response, '<form class="fair-assistant-form">', count=1)
                self.assertContains(response, 'data-object-id=""')
                context = "upload" if name == "upload_json" else "search"
                self.assertContains(response, f'data-page="{context}"')
        response = self.client.get("/charts/")
        self.assertContains(response, 'class="fair-assistant-widget"', count=1)

    def test_detail_keeps_object_context(self):
        """
        Preserve object specific suggestions after moving to the shared layout
        """
        self.client.force_login(self.owner)
        response = self.client.get(reverse("json_data_detail", args=[self.obj.pk]))
        self.assertContains(response, 'class="fair-assistant-widget"', count=1)
        self.assertContains(response, 'data-page="detail"')
        self.assertContains(response, f'data-object-id="{self.obj.pk}"')
        self.assertContains(response, 'data-question="Summarize this data"')

    def test_public_pages_do_not_show_assistant(self):
        """
        Keep the assistant out of public introduction and authentication pages
        """
        for name in ("index", "login", "register"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertNotContains(response, 'class="fair-assistant-widget"')
                self.assertNotContains(response, '<form class="fair-assistant-form">')
        response = self.client.post(
            reverse("fair_assistant_ask"),
            data=json.dumps({"question": "How do I search?"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.owner)
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="fair-assistant-widget"')

    def test_new_entry_pages_supply_csrf_for_questions(self):
        """
        Allow a first assistant question from pages without other forms
        """
        for name in ("json_data_list", "notification_list"):
            with self.subTest(page=name):
                client = Client(enforce_csrf_checks=True)
                client.force_login(self.owner)
                response = client.get(reverse(name), follow=True)
                self.assertEqual(response.status_code, 200)
                token = client.cookies["csrftoken"].value
                response = client.post(
                    reverse("fair_assistant_ask"),
                    data=json.dumps({"question": "How do I search?", "page": "search"}),
                    content_type="application/json", HTTP_X_CSRFTOKEN=token,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["answer"])
