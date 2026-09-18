import weakref

from django.contrib.auth.models import User
from django.db.models.signals import post_init
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


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
