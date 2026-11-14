"""
Exercise fresh signed navigation without raw data reads or permission changes.
"""

from django.contrib.auth.models import User
from django.core import signing
from django.http import QueryDict
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .collection_navigation import CONTEXT_SALT, read_navigation
from .models import CollectionRelationship, JSONData, ResearchCollection
from .study_navigation import curve_presentation_parameters


class StudyNavigationTests(TestCase):
    """
    Retain explicit presentation choices only within authorized study scopes.
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create owned, public and unavailable source records.
        """
        cls.owner = User.objects.create_user(username="state-owner")
        cls.other = User.objects.create_user(username="state-other")
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Private study")
        cls.first = JSONData.objects.create(owner=cls.owner, data={"title": "Owned"})
        cls.second = JSONData.objects.create(owner=cls.other, access_type="all", data={"title": "Public"})
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "HIDDEN SOURCE"})
        cls.collection.members.add(cls.first, cls.second, cls.hidden)

    def setUp(self):
        """
        Authenticate the collection owner for each independent request.
        """
        self.client.force_login(self.owner)
        self.url = reverse("collection_study_navigation", args=[self.collection.pk])
        self.state = {"panel": "compare", "compare": f"{self.second.pk},{self.first.pk}",
                      "inspect": "1", "detail_status": "different", "detail_q": "C11",
                      "curve_open": "1", "curve_view": "overlay"}

    def test_refresh_signs_display_state_and_preserves_reference_order(self):
        """
        Generate owner-bound tokens for the visible controls and graph variants.
        """
        response = self.client.get(self.url, self.state)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        payload = signing.loads(response.json()["graph_context"], salt=CONTEXT_SALT)
        self.assertEqual(payload["user"], self.owner.pk)
        self.assertEqual(payload["params"], self.state)
        detailed = signing.loads(response.json()["variants"]["detailed"], salt=CONTEXT_SALT)
        self.assertEqual(detailed["params"]["view"], "detailed")

    def test_refresh_rechecks_the_complete_current_selection(self):
        """
        Access revocation fails instead of signing a partial comparison.
        """
        self.second.access_type = "c"
        self.second.save(update_fields=["access_type"])
        response = self.client.get(self.url, self.state)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("graph_context", response.json())
        self.assertNotContains(response, "HIDDEN SOURCE", status_code=400)

    def test_unknown_repeated_or_invalid_options_are_rejected(self):
        """
        Reject ambiguous controls before any token is created.
        """
        queries = ["redirect=https://example.test", "curve_open=1&curve_open=0", "detail_q=" + "x" * 201,
                   "curve_view=invalid", "analysis=0", "compare=1,1", "detail_focus=bad"]
        for query in queries:
            with self.subTest(query=query[:70]):
                self.assertEqual(self.client.get(self.url + "?" + query).status_code, 400)

    def test_other_owners_and_mutating_methods_are_unavailable(self):
        """
        Keep the endpoint read-only and scoped to the private collection owner.
        """
        self.assertEqual(self.client.post(self.url, self.state).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url, self.state).status_code, 404)

    def test_temporary_refresh_rechecks_even_unpinned_members(self):
        """
        An expired permission anywhere in a temporary scope invalidates refresh.
        """
        created = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [self.first.pk, self.second.pk],
        })
        token = created.url.rstrip("/").split("/")[-1]
        url = reverse("selection_study_navigation", args=[token])
        self.assertEqual(self.client.get(url, {"compare": str(self.first.pk)}).status_code, 200)
        self.second.access_type = "c"
        self.second.save(update_fields=["access_type"])
        self.assertEqual(self.client.get(url, {"compare": str(self.first.pk)}).status_code, 400)

    def test_curve_presentation_defaults_and_explicit_closed_state(self):
        """
        Preserve an explicit closed panel without adding default presentation noise.
        """
        self.assertEqual(curve_presentation_parameters({}), {})
        self.assertEqual(curve_presentation_parameters({"curve_view": "separate", "curve_open": "0"}), {"curve_open": "0"})
        with self.assertRaises(ValueError):
            curve_presentation_parameters(QueryDict("curve_view=overlay&curve_view=separate"))

    def test_maximal_multibyte_search_state_survives_signed_source_return(self):
        """
        Valid Unicode searches fit both refreshed and legacy uncompressed tokens.
        """
        state = {**self.state, "member_q": "".join(chr(0x4e00 + index * 37) for index in range(200)),
                 "detail_q": "".join(chr(0x6000 + index * 31) for index in range(200)),
                 "map_unit": "a" * 64, "map_cell": "b" * 64, "map_x_page": "2147483647",
                 "map_y_page": "2147483647", "page": "2147483647", "groups_page": "2147483647",
                 "relationships_page": "2147483647", "curve_component": "equivalent", "curve_strain": "plastic"}
        state.update(find_candidates="1", match_fields="software,phase,elastic_model,plastic_model,discretization_type,discretization_count", vary_field="temperature")
        response = self.client.get(self.url, state)
        self.assertEqual(response.status_code, 200)
        payload = {"user": self.owner.pk, "kind": "collection", "target": self.collection.pk, "params": state}
        uncompressed = signing.dumps(payload, salt=CONTEXT_SALT)
        self.assertGreater(len(uncompressed), 4096)
        for token in (uncompressed, response.json()["graph_context"]):
            request = RequestFactory().get("/", {"graph_context": token})
            request.user = self.owner
            self.assertEqual(read_navigation(request)["params"], state)

    def test_native_detail_filters_retain_manual_relationship_page(self):
        """
        Preserve a collection's relationship position while changing detail filters.
        """
        for index in range(13):
            CollectionRelationship.objects.create(collection=self.collection, source=self.first,
                                                  target=self.second, label=f"Recorded link {index}")
        url = reverse("collection_detail", args=[self.collection.pk])
        response = self.client.get(url, {**self.state, "relationships_page": "2"})
        filters = response.context["study_details"]["navigation"]["filters"]
        changed = self.client.get(filters[0]["url"])
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.context["manual_editor"]["page"].number, 2)
