"""
Verify cached collection labels avoid reading arrays and remain current and private
"""

from copy import deepcopy
from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.http import QueryDict
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .collection_graph import CollectionSummaryPending, build_collection_context, collection_summaries
from .collection_summary import build_collection_summary
from .models import JSONData, ResearchCollection
from .research_collections import accessible_objects


class CollectionSummaryTests(TestCase):
    """
    Exercise persisted summaries across writes, legacy rows and permission changes
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create synthetic metadata and independent owners without external fixtures
        """
        cls.owner = User.objects.create_user(username="summary-owner")
        cls.viewer = User.objects.create_user(username="summary-viewer")
        cls.metadata = {
            "Identifier": "cached-run", "Title": "Copper cyclic run",
            "Software Name": "DAMASK", "Software version": "3.0",
            "Creator Name": "Recorded creator",
            "Phase": [{"Phase name": "Copper"}],
            "Relation": ["10.1234/Study", "https://doi.org/10.1234/study"],
            "Mechanical BC": [{"Loading type": "stress", "Loading mode": "cyclic"}],
            "stress": {"stress_11": list(range(10000))},
            "total_strain": {"strain_11": list(range(10000))},
            "extra": {"unchanged": [False, 0, "Original value"]},
        }
        cls.record = JSONData.objects.create(
            owner=cls.owner, data=cls.metadata, size_bytes=len(json.dumps(cls.metadata).encode()),
        )

    def graph(self, queryset=None):
        """
        Build the member view from an explicitly accessible queryset

        Parameters
        ----------
        queryset : QuerySet or None, optional
            Alternative access scope for a permission regression.

        Returns
        -------
        dict
            Collection graph and supplied object summaries.
        """
        if queryset is None:
            queryset = accessible_objects(self.owner)
        return build_collection_context(
            queryset, title="Cached collection", base_url="/graph/collections/1/",
            params=QueryDict("links=members"),
        )

    def test_warm_graph_queries_do_not_select_raw_json(self):
        """
        Keep array bytes outside every query used to render an existing summary
        """
        with CaptureQueriesContext(connection) as queries:
            result = self.graph()
        self.assertEqual(result["object_rows"][0]["title"], "Copper cyclic run")
        self.assertEqual(len(queries), 1)
        self.assertIn('"collection_summary"', queries[0]["sql"])
        self.assertNotIn('"pages_jsondata"."data"', queries[0]["sql"])

    def test_summary_preserves_supplied_meaning_without_arrays_or_record_urls(self):
        """
        Retain complete labels and exact grouping while leaving original JSON intact
        """
        original = deepcopy(self.metadata)
        summary = build_collection_summary(original)
        self.assertEqual(summary["software"], "DAMASK")
        self.assertEqual(summary["software_version"], "3.0")
        self.assertEqual(summary["phase"], "Copper")
        self.assertEqual(summary["loading"], "stress · cyclic")
        self.assertEqual(summary["creator"], "Recorded creator")
        self.assertEqual(summary["groups"]["relations"], {"doi:10.1234/study": "10.1234/Study"})
        self.assertEqual(original, self.metadata)
        self.assertNotIn("pk", summary)
        self.assertNotIn("detail_url", summary)
        self.assertNotIn("stress", summary)
        self.assertNotIn("total_strain", summary)
        self.assertNotIn("extra", summary)
        self.assertTrue(all(isinstance(value, str) for key, value in summary.items()
                            if key not in {"groups", "summary_version", "comparison"}))
        self.assertEqual(summary["summary_version"], 2)
        self.record.refresh_from_db()
        self.assertEqual(self.record.data, original)
        self.assertEqual(self.record.collection_summary, summary)

    def test_data_save_refreshes_summary_and_keeps_access_only_save_small(self):
        """
        Update derived labels together with data without fetching data for access edits
        """
        self.record.data = {"title": "New supplied title", "software": "Abaqus"}
        self.record.save(update_fields=["data"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.collection_summary["title"], "New supplied title")
        obj = JSONData.objects.only("pk", "access_type").get(pk=self.record.pk)
        obj.access_type = "all"
        with CaptureQueriesContext(connection) as queries:
            obj.save(update_fields=["access_type"])
        self.assertEqual(len(queries), 1)
        self.assertNotIn('"data"', queries[0]["sql"])
        self.assertNotIn('"collection_summary"', queries[0]["sql"])
        self.assertEqual(self.graph()["object_rows"][0]["title"], "New supplied title")

    def test_deferred_save_does_not_load_or_replace_data(self):
        """
        Preserve Django deferred writes without fetching a large JSON field
        """
        obj = JSONData.objects.only("pk", "access_type").get(pk=self.record.pk)
        obj.access_type = "all"
        with CaptureQueriesContext(connection) as queries:
            obj.save()
        self.assertEqual(len(queries), 1)
        self.assertNotIn('"data"', queries[0]["sql"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.data, self.metadata)
        self.assertEqual(self.record.collection_summary["title"], "Copper cyclic run")

    def test_stale_deferred_save_cannot_restore_an_old_summary(self):
        """
        Preserve a concurrent data change when a deferred instance edits access
        """
        stale = JSONData.objects.defer("data").get(pk=self.record.pk)
        self.assertEqual(stale.collection_summary["title"], "Copper cyclic run")
        JSONData.objects.filter(pk=self.record.pk).update(data={"title": "Current supplied title"})
        self.assertEqual(self.graph()["object_rows"][0]["title"], "Current supplied title")
        stale.access_type = "all"
        with CaptureQueriesContext(connection) as queries:
            stale.save()
        self.record.refresh_from_db()
        self.assertEqual(self.record.collection_summary["title"], "Current supplied title")
        self.assertEqual(self.record.data, {"title": "Current supplied title"})
        self.assertEqual(self.record.access_type, "all")
        self.assertEqual(len(queries), 1)
        self.assertNotIn('"collection_summary"', queries[0]["sql"])
        self.assertNotIn('"data"', queries[0]["sql"])

    def test_queryset_data_update_invalidates_and_lazy_read_prepares_only_once(self):
        """
        Never show cached old labels after an update that bypasses model save
        """
        JSONData.objects.filter(pk=self.record.pk).update(data={"title": "Updated directly"})
        self.record.refresh_from_db()
        self.assertIsNone(self.record.collection_summary)
        with CaptureQueriesContext(connection) as queries:
            result = self.graph()
        self.assertEqual(result["object_rows"][0]["title"], "Updated directly")
        self.assertEqual(sum(item["sql"].startswith(
            'SELECT "pages_jsondata"."id", "pages_jsondata"."data"',
        ) for item in queries), 1)
        self.record.refresh_from_db()
        self.assertEqual(self.record.collection_summary["title"], "Updated directly")
        with CaptureQueriesContext(connection) as warm:
            self.graph()
        self.assertEqual(len(warm), 1)
        self.assertNotIn('"pages_jsondata"."data"', warm[0]["sql"])

    def test_bulk_create_and_bulk_data_update_maintain_cache(self):
        """
        Populate inserted summaries and invalidate Case expressions during bulk updates
        """
        records = JSONData.objects.bulk_create([
            JSONData(owner=self.owner, data={"title": "Bulk A"}, size_bytes=19),
            JSONData(owner=self.owner, data={"title": "Bulk B"}, size_bytes=19),
        ])
        self.assertEqual(
            set(JSONData.objects.filter(pk__in=[obj.pk for obj in records]).values_list(
                "collection_summary__title", flat=True,
            )), {"Bulk A", "Bulk B"},
        )
        for index, obj in enumerate(records):
            obj.data = {"title": f"Changed bulk {index}"}
        JSONData.objects.bulk_update(records, ["data"])
        self.assertEqual(JSONData.objects.filter(
            pk__in=[obj.pk for obj in records], collection_summary__isnull=True,
        ).count(), 2)
        self.assertEqual(
            {row["title"] for row in self.graph()["object_rows"]},
            {"Copper cyclic run", "Changed bulk 0", "Changed bulk 1"},
        )

    def test_bulk_conflict_update_refreshes_summary_with_data(self):
        """
        Keep summaries consistent when an existing record is updated on insertion
        """
        JSONData.objects.bulk_create([
            JSONData(pk=self.record.pk, owner=self.owner, data={"title": "Upsert title"}),
        ], update_conflicts=True, update_fields=["data"], unique_fields=["pk"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.data["title"], "Upsert title")
        self.assertEqual(self.record.collection_summary["title"], "Upsert title")

    def test_access_changes_do_not_invalidate_cache_or_reveal_private_rows(self):
        """
        Apply current permissions before cached summary lookup and legacy preparation
        """
        self.record.shared_users.add(self.viewer)
        self.assertEqual(self.graph(accessible_objects(self.viewer))["object_total"], 1)
        self.record.shared_users.clear()
        with CaptureQueriesContext(connection) as queries:
            result = self.graph(accessible_objects(self.viewer))
        self.assertEqual(result["object_total"], 0)
        self.assertNotIn("Copper cyclic run", str(result))
        self.assertTrue(all('"pages_jsondata"."data"' not in item["sql"] for item in queries))
        JSONData.objects.filter(pk=self.record.pk).update(collection_summary=None)
        with patch("apps.pages.collection_graph.build_collection_summary") as builder:
            self.assertEqual(self.graph(accessible_objects(self.viewer))["object_total"], 0)
            builder.assert_not_called()
        self.record.refresh_from_db()
        self.assertIsNone(self.record.collection_summary)

    def test_cached_summary_mutation_does_not_change_persisted_metadata(self):
        """
        Allow graph grouping to consume runtime fields without altering the cache
        """
        first = list(collection_summaries(accessible_objects(self.owner)))[0]
        first.pop("groups")
        self.record.refresh_from_db()
        self.assertIn("groups", self.record.collection_summary)
        self.assertEqual(self.graph()["object_rows"][0]["phase"], "Copper")

    def test_backfill_command_is_bounded_and_restartable(self):
        """
        Prepare old records in small batches while preserving source JSON and caches
        """
        second = JSONData.objects.create(owner=self.owner, data={"title": "Another old record"})
        JSONData.objects.filter(pk__in=[self.record.pk, second.pk]).update(collection_summary=None)
        first_output = StringIO()
        call_command("backfill_collection_summaries", limit=1, stdout=first_output)
        self.assertIn("Prepared 1 summaries. 1 records still need summaries.", first_output.getvalue())
        self.record.refresh_from_db()
        self.assertEqual(self.record.data, self.metadata)
        self.assertIsNotNone(self.record.collection_summary)
        next_output = StringIO()
        call_command("backfill_collection_summaries", limit=1, stdout=next_output)
        self.assertIn("Prepared 1 summaries. 0 records still need summaries.", next_output.getvalue())
        with self.assertRaises(CommandError):
            call_command("backfill_collection_summaries", limit=0)

    def test_backfill_all_uses_bounded_batches_and_a_fixed_initial_upper_bound(self):
        """
        Finish existing records without chasing rows inserted during preparation
        """
        JSONData.objects.bulk_create([
            JSONData(owner=self.owner, data={"title": f"Old record {index}"}) for index in range(204)
        ])
        JSONData.objects.all().update(collection_summary=None)
        batch_sizes = []
        inserted = []

        def prepare_batch(queryset, *, prepare_all=False, require_comparison=False):
            """
            Observe real batches while introducing a new record after the first

            Parameters
            ----------
            queryset : QuerySet
                Current batch selected by the management command.
            prepare_all : bool, optional
                Whether operator preparation bypasses the web request allowance.
            require_comparison : bool, optional
                Whether outdated comparison projections are also prepared.

            Returns
            -------
            iterator
                Summaries prepared by the actual implementation.
            """
            batch_sizes.append(queryset.count())
            summaries = list(collection_summaries(queryset, prepare_all=prepare_all,
                                                require_comparison=require_comparison))
            if len(batch_sizes) == 1:
                obj = JSONData.objects.create(owner=self.owner, data={"title": "Inserted after command start"})
                JSONData.objects.filter(pk=obj.pk).update(collection_summary=None)
                inserted.append(obj.pk)
            return iter(summaries)

        output = StringIO()
        with patch("apps.pages.management.commands.backfill_collection_summaries.collection_summaries",
                   side_effect=prepare_batch):
            call_command("backfill_collection_summaries", all=True, stdout=output)
        self.assertEqual(batch_sizes, [100, 100, 5])
        self.assertIn("Prepared 205 summaries. 1 records still need summaries.", output.getvalue())
        self.assertEqual(list(JSONData.objects.filter(
            collection_summary__isnull=True,
        ).values_list("pk", flat=True)), inserted)
        self.record.refresh_from_db()
        self.assertEqual(self.record.data, self.metadata)
        resumed = StringIO()
        call_command("backfill_collection_summaries", all=True, stdout=resumed)
        self.assertIn("Prepared 1 summaries. 0 records still need summaries.", resumed.getvalue())

    def test_web_preparation_limits_rows_and_never_returns_a_partial_graph(self):
        """
        Show real progress after one bounded batch and render only when complete
        """
        records = JSONData.objects.bulk_create([
            JSONData(owner=self.owner, data={"title": f"Legacy {index}"}, size_bytes=22)
            for index in range(30)
        ])
        ids = [obj.pk for obj in records]
        JSONData.objects.filter(pk__in=ids).update(collection_summary=None)
        collection = ResearchCollection.objects.create(owner=self.owner, title="Preparing collection")
        collection.members.add(*records)
        self.client.force_login(self.owner)
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_SECONDS", 60):
            with CaptureQueriesContext(connection) as queries:
                pending = self.client.get(reverse("collection_detail", args=[collection.pk]))
        self.assertEqual(pending.status_code, 202)
        self.assertEqual(pending.context["summary_preparation"], {
            "ready_count": 25, "total_count": 30, "requires_admin": False,
        })
        self.assertEqual(pending.context["object_rows"], [])
        self.assertIsNone(pending.context["relationship_graph"])
        self.assertEqual(sum(item["sql"].startswith(
            'SELECT "pages_jsondata"."id", "pages_jsondata"."data"',
        ) for item in queries), 25)
        ready = self.client.get(reverse("collection_detail", args=[collection.pk]))
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.context["object_total"], 30)
        self.assertNotIn("summary_preparation", ready.context)

    def test_web_preparation_enforces_total_actual_bytes(self):
        """
        Stop before loading a second raw object that exceeds the remaining budget
        """
        data = {"title": "One legacy record", "unknown": "x" * 700}
        records = JSONData.objects.bulk_create([
            JSONData(owner=self.owner, data=data, size_bytes=len(json.dumps(data).encode()))
            for _ in range(3)
        ])
        queryset = JSONData.objects.filter(pk__in=[obj.pk for obj in records])
        queryset.update(collection_summary=None)
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_BYTES", 1024):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(CollectionSummaryPending) as raised:
                    self.graph(queryset)
        self.assertEqual(raised.exception.ready_count, 1)
        self.assertEqual(raised.exception.total_count, 3)
        self.assertFalse(raised.exception.requires_admin)
        self.assertEqual(sum(item["sql"].startswith(
            'SELECT "pages_jsondata"."id", "pages_jsondata"."data"',
        ) for item in queries), 1)

    def test_unknown_or_oversized_records_require_operator_without_raw_fetch(self):
        """
        Avoid reading an unbounded JSON while keeping hidden records out of progress
        """
        for size in (0, 2048):
            with self.subTest(size=size):
                JSONData.objects.filter(pk=self.record.pk).update(collection_summary=None, size_bytes=size)
                hidden = JSONData.objects.create(owner=self.viewer, data={"title": "Hidden record"}, size_bytes=0)
                JSONData.objects.filter(pk=hidden.pk).update(collection_summary=None)
                collection = ResearchCollection.objects.create(owner=self.owner, title="Operator preparation")
                collection.members.add(self.record, hidden)
                self.client.force_login(self.owner)
                with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_BYTES", 1024):
                    with CaptureQueriesContext(connection) as queries:
                        response = self.client.get(reverse("collection_detail", args=[collection.pk]))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.context["summary_preparation"], {
                    "ready_count": 0, "total_count": 1, "requires_admin": True,
                })
                self.assertNotContains(response, "Hidden record", status_code=503)
                self.assertFalse(any(item["sql"].startswith(
                    'SELECT "pages_jsondata"."id", "pages_jsondata"."data"',
                ) for item in queries))

    def test_stale_size_cannot_allow_an_oversized_raw_data_fetch(self):
        """
        Measure actual database bytes before reading data after a direct update
        """
        JSONData.objects.filter(pk=self.record.pk).update(size_bytes=64)
        JSONData.objects.filter(pk=self.record.pk).update(data={"title": "Changed", "unknown": "x" * 2048})
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_BYTES", 1024):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(CollectionSummaryPending) as raised:
                    self.graph()
        self.assertTrue(raised.exception.requires_admin)
        self.assertEqual(raised.exception.ready_count, 0)
        self.assertEqual(raised.exception.total_count, 1)
        self.assertFalse(any(item["sql"].startswith(
            'SELECT "pages_jsondata"."id", "pages_jsondata"."data"',
        ) for item in queries))
        self.record.refresh_from_db()
        self.assertEqual(self.record.size_bytes, 64)
        call_command("backfill_collection_summaries", all=True, stdout=StringIO())
        self.assertEqual(self.graph()["object_rows"][0]["title"], "Changed")

    def test_web_size_check_uses_utf8_bytes_instead_of_character_count(self):
        """
        Keep multibyte metadata within the same byte allowance as ASCII metadata
        """
        JSONData.objects.filter(pk=self.record.pk).update(size_bytes=64)
        JSONData.objects.filter(pk=self.record.pk).update(data={"title": "Copper", "unknown": "铜" * 500})
        with patch("apps.pages.collection_graph.MAX_REQUEST_SUMMARY_BYTES", 1024):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(CollectionSummaryPending) as raised:
                    self.graph()
        self.assertTrue(raised.exception.requires_admin)
        self.assertFalse(any(item["sql"].startswith(
            'SELECT "pages_jsondata"."id", "pages_jsondata"."data"',
        ) for item in queries))

    def test_invalid_save_retains_error_status_during_summary_preparation(self):
        """
        Keep rejected form feedback visible when the graph also needs preparation
        """
        self.client.force_login(self.owner)
        selection = self.client.post(reverse("graph_selection_create"), {"selected_objects": [self.record.pk]})
        token = selection.url.rstrip("/").rsplit("/", 1)[-1]
        JSONData.objects.filter(pk=self.record.pk).update(collection_summary=None, size_bytes=0)
        response = self.client.post(reverse("collection_save", args=[token]), {"title": ""})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context["collection_form"].errors["title"])
        self.assertContains(response, "This field is required.", status_code=400)
        self.assertTrue(response.context["summary_preparation"]["requires_admin"])
        self.assertContains(response, f'href="{selection.url}"', status_code=400)
