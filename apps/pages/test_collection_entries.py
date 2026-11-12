import re

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class CollectionEntryTests(TestCase):
    """
    Exercise collection entry points and the local graph tab through real views
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create a private record with metadata and a distinctive curve sample
        """
        cls.owner = User.objects.create_user(username="collection-entry-owner")
        cls.reader = User.objects.create_user(username="collection-entry-reader")
        cls.record = JSONData.objects.create(
            owner=cls.owner,
            access_type="c",
            data={
                "identifier": "collection-entry-record",
                "title": "Copper collection study",
                "creator": "Recorded researcher",
                "software": "DAMASK",
                "phase": [{"phase_name": "Copper"}],
                "stress": {"stress_11": [0, 123456789.123456]},
            },
        )

    def setUp(self):
        """
        Sign in as the record owner before each entry flow
        """
        self.client.force_login(self.owner)

    def test_list_selection_buttons_work_without_javascript(self):
        """
        Submit displayed selections through the existing CSRF protected forms
        """
        pages = [
            (reverse("search") + "?keyword=copper", "graphSelectedButton"),
            (reverse("json_data_list"), "graphMyDataButton"),
        ]
        for url, button_id in pages:
            with self.subTest(page=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                button = re.search(
                    rf'<button\b[^>]*\bid="{button_id}"[^>]*>',
                    response.content.decode(),
                )
                self.assertIsNotNone(button)
                self.assertIn(
                    f'formaction="{reverse("graph_selection_create")}"',
                    button.group(),
                )
                self.assertNotIn("disabled", button.group())
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                self.assertContains(response, 'name="selected_objects"')

    def test_collection_success_messages_show_on_the_destination_once(self):
        """
        Show save and delete feedback immediately without carrying it into Search
        """
        selected = self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.record.pk]})
        token = selected.url.rstrip("/").split("/")[-1]
        saved = self.client.post(reverse("collection_save", args=[token]), {"title": "Feedback study"})
        destination = self.client.get(saved.url)
        self.assertContains(destination, "Research collection saved. Only you can access this collection.")
        self.assertNotContains(self.client.get(saved.url), "Research collection saved.")
        collection = destination.context["collection"]
        deleted = self.client.post(reverse("collection_delete", args=[collection.pk]))
        self.assertContains(self.client.get(deleted.url), "Collection deleted. Its data objects are unchanged.")
        later = self.client.get(reverse("search"))
        self.assertNotContains(later, "Research collection saved.")
        self.assertNotContains(later, "Collection deleted. Its data objects are unchanged.")

    def test_detail_graph_tab_does_not_copy_curves_or_load_plot_scripts(self):
        """
        Render the same record locally while keeping large plot data off Graph
        """
        url = reverse("json_data_detail", args=[self.record.pk])
        response = self.client.get(url, {"tab": "graph"})
        self.assertContains(response, 'id="detail-relationships"')
        self.assertContains(response, "Recorded researcher")
        self.assertContains(response, "detail-relationships.js")
        self.assertContains(response, f'href="{url}" class="nav-link"')
        self.assertContains(response, 'id="detail-open-graph"')
        self.assertNotContains(response, 'id="plot-variables-data"')
        self.assertNotContains(response, "123456789.123456")
        self.assertNotContains(response, "mechanical-bc-viewer.js")
        self.assertNotContains(response, "cdn.jsdelivr.net/npm/chart.js")
        self.assertNotContains(response, 'id="data-metadata"')

    def test_default_details_keep_metadata_and_graph_navigation(self):
        """
        Retain the normal detail view and its links when no tab is requested
        """
        url = reverse("json_data_detail", args=[self.record.pk])
        response = self.client.get(url)
        self.assertContains(response, 'id="data-metadata"')
        self.assertContains(response, 'id="plot-variables-data"')
        self.assertContains(response, f'href="{url}?tab=graph"')
        self.assertContains(response, f'href="/graph/?object={self.record.pk}"')
        self.assertNotContains(response, 'id="detail-relationships"')

    def test_detailed_graph_links_stay_on_the_selected_record_tab(self):
        """
        Keep native presentation links within the local graph view
        """
        url = reverse("json_data_detail", args=[self.record.pk])
        response = self.client.get(url, {"tab": "graph", "view": "detailed"})
        self.assertEqual(response.context["relationship_graph"]["view"], "detailed")
        self.assertContains(response, f'href="{url}?tab=graph&amp;view=compact"')
        self.assertContains(response, f'href="{url}?tab=graph&amp;view=detailed"')

    def test_detail_graph_uses_existing_record_access_rules(self):
        """
        Reject an unshared private graph and allow explicit shares and public data
        """
        url = reverse("json_data_detail", args=[self.record.pk])
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(url, {"tab": "graph"}).status_code, 404)
        self.record.shared_users.add(self.reader)
        self.assertContains(self.client.get(url, {"tab": "graph"}), "Recorded researcher")
        self.record.shared_users.clear()
        self.record.access_type = "all"
        self.record.save(update_fields=["access_type"])
        self.assertContains(self.client.get(url, {"tab": "graph"}), "Recorded researcher")
        self.client.logout()
        self.assertEqual(self.client.get(url, {"tab": "graph"}).status_code, 302)
