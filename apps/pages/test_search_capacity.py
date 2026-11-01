import cProfile
import weakref

from django.contrib.auth.models import User
from django.db import connection
from django.db.models.signals import post_init
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.dyn_api.metadata_compat import metadata_view
from .models import JSONData
from .views import _is_number_value


class SearchCapacityTests(TestCase):
    """
    Keep large JSON payloads out of accumulated search results
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create matching records with a sizable field absent from list summaries
        """
        cls.viewer = User.objects.create_user(username="capacity_viewer")
        cls.owner = User.objects.create_user(username="capacity_owner")
        cls.records = []
        for index in range(8):
            cls.records.append(JSONData.objects.create(
                owner=cls.owner,
                access_type="all",
                data={
                    "identifier": f"capacity-{index}",
                    "title": f"Copper specimen {index}",
                    "creator": ["Ronak Shoghi"],
                    "date": "2026-09-19",
                    "software": "DAMASK solver",
                    "keywords": ["crystal", "plasticity"],
                    "phase": [{"grain_number": 75}],
                    "bulk_data": "large optional content " * 1000,
                },
            ))

    def setUp(self):
        """
        Authenticate the viewer for each real search request
        """
        self.client.force_login(self.viewer)

    def test_105_matches_do_not_add_one_database_query_per_object(self):
        """
        Keep database round trips bounded as the result set grows
        """
        extra = []
        for index in range(8, 105):
            extra.append(JSONData(
                owner=self.owner, access_type="all",
                data={**self.records[0].data, "identifier": f"capacity-{index}"},
            ))
        JSONData.objects.bulk_create(extra)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("search"), {"keyword": "copper specimen"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result_count"], 105)
        self.assertLessEqual(len(queries), 10)

    def test_private_searches_keep_permissions_and_badges_with_bounded_queries(self):
        """
        Preserve private access and current sharing labels without per row lookups
        """
        own = JSONData.objects.create(owner=self.viewer, data={"title": "Copper owned"})
        received = JSONData.objects.create(owner=self.owner, data={"title": "Copper received"})
        hidden = JSONData.objects.create(owner=self.owner, data={"title": "Copper hidden"})
        own.shared_users.add(self.owner)
        received.shared_users.add(self.viewer, self.owner)
        hidden.shared_users.add(self.owner)
        public_ids = {obj.pk for obj in self.records}
        for scope, expected in (
            ("", public_ids | {own.pk, received.pk}),
            ("public", public_ids),
            ("my_data", {own.pk}),
            ("my_private", {own.pk}),
            ("shared_with_me", {received.pk}),
        ):
            with self.subTest(scope=scope):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(reverse("search"), {"keyword": "copper", "access": scope})
                results = response.context["data_objects"]
                self.assertEqual({obj.pk for obj in results}, expected)
                self.assertEqual(len(results), len(expected))
                for obj in results:
                    access = next(field for field in obj.summary_fields if field["label"] == "Access")
                    self.assertEqual(access["badges"], ["Public"] if obj.pk in public_ids else ["Private", "Shared"])
                self.assertLessEqual(len(queries), 10)
        received.shared_users.remove(self.viewer)
        own.shared_users.clear()
        response = self.client.get(reverse("search"), {"keyword": "copper"})
        self.assertEqual({obj.pk for obj in response.context["data_objects"]}, public_ids | {own.pk})
        result = next(obj for obj in response.context["data_objects"] if obj.pk == own.pk)
        access = next(field for field in result.summary_fields if field["label"] == "Access")
        self.assertEqual(access["badges"], ["Private"])

    def test_keyword_search_normalizes_each_object_at_most_once(self):
        """
        Reuse recognized metadata between filtering and summary rendering
        """
        with cProfile.Profile() as profile:
            response = self.client.get(reverse("search"), {"keyword": "copper specimen"})
        self.assertEqual(response.context["result_count"], 8)
        calls = sum(entry.callcount for entry in profile.getstats() if entry.code == metadata_view.__code__)
        self.assertLessEqual(calls, 8)

    def test_keyword_search_does_not_classify_every_plain_curve_number(self):
        """
        Avoid expensive numeric type dispatch for every sample in keyword searches
        """
        obj = self.records[0]
        obj.data["stress"] = {"stress_11": [index / 100 for index in range(4096)]}
        obj.save(update_fields=["data"])
        with cProfile.Profile() as profile:
            response = self.client.get(reverse("search"), {"keyword": "copper specimen"})
        self.assertEqual(response.context["result_count"], 8)
        calls = sum(entry.callcount for entry in profile.getstats() if entry.code == _is_number_value.__code__)
        self.assertLess(calls, 1000)
        self.assertEqual(JSONData.objects.get(pk=obj.pk).data, obj.data)

    def test_unmatched_payloads_are_released_during_the_scan(self):
        """
        Avoid retaining the original payloads of every nonmatch during a scan
        """
        loaded = []
        peak_loaded = 0

        def observe_loaded_object(sender, instance, **kwargs):
            """
            Count live raw payloads without retaining their model instances

            Parameters
            ----------
            sender : type
                Model emitting the initialization signal.
            instance : JSONData
                Newly initialized database object.
            **kwargs : dict
                Additional signal metadata.
            """
            nonlocal peak_loaded
            loaded.append(weakref.ref(instance))
            live_count = 0
            for reference in loaded:
                obj = reference()
                if obj is not None and "bulk_data" in obj.data:
                    live_count += 1
            peak_loaded = max(peak_loaded, live_count)

        post_init.connect(observe_loaded_object, sender=JSONData, weak=False)
        try:
            response = self.client.get(reverse("search"), {"keyword": "nonexistent"})
        finally:
            post_init.disconnect(observe_loaded_object, sender=JSONData)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result_count"], 0)
        self.assertEqual(len(loaded), 8)
        self.assertLessEqual(peak_loaded, 2)

    def test_results_keep_summaries_without_retaining_raw_json(self):
        """
        Preserve filtering and rendered metadata while releasing large fields
        """
        response = self.client.get(reverse("search"), {
            "keyword": "SPECIMEN copper",
            "creator": "SHOGHI ronak",
            "software": "solver damask",
            "access": "public",
            "condition_field": "grain_count",
            "condition_operator": "gte",
            "condition_value": "50",
        })

        self.assertEqual(response.status_code, 200)
        results = response.context["data_objects"]
        self.assertEqual(response.context["result_count"], 8)
        self.assertEqual([obj.pk for obj in results], [obj.pk for obj in reversed(self.records)])
        for obj in results:
            with self.subTest(identifier=obj.data.get("identifier")):
                self.assertNotIn("bulk_data", list(obj.data))
                self.assertContains(response, obj.data["identifier"])
                self.assertContains(response, obj.search_display_name)
                self.assertContains(response, reverse("json_data_detail", args=[obj.pk]))
        for text in ("Ronak Shoghi", "2026-09-19", "DAMASK solver", "crystal", "plasticity", "Public"):
            self.assertContains(response, text)

        stored = JSONData.objects.get(pk=self.records[0].pk)
        self.assertEqual(stored.data, self.records[0].data)
