import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData, ResearchCollection
from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class CollectionBrowserTests(StaticLiveServerTestCase):
    """
    Exercise complete collection workflows and bounded desktop graphs in Chromium
    """

    server_thread_class = PlotLiveServerThread

    def test_collection_workflow_and_native_fallback(self):
        """
        Save, inspect and manage selected records with and without JavaScript
        """
        self.assertTrue(shutil.which("node"), "Collection browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="collection-browser-viewer")
        other = User.objects.create_user(username="collection-browser-other")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        first_data = {
            "identifier": "workflow-first", "title": "Workflow copper baseline",
            "creator": "Recorded researcher", "software": "DAMASK", "software_version": "3.0",
            "phase": [{"phase_name": "Copper"}], "relation": ["10.1234/collection.study"],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "static"}],
        }
        first = JSONData.objects.create(owner=viewer, data=first_data)
        second = JSONData.objects.create(owner=viewer, data={
            "identifier": "workflow-second", "title": "Workflow copper additional run",
            "software": "Append Solver", "phase": [{"phase_name": "Copper"}],
            "relation": ["https://doi.org/10.1234/collection.study"],
        })
        public = JSONData.objects.create(owner=other, access_type="all", data={
            "identifier": "workflow-public", "title": "Workflow public reference",
            "software": "DAMASK", "phase": [{"phase_name": "Copper"}],
            "relation": ["doi:10.1234/collection.study"],
        })
        shared = JSONData.objects.create(owner=other, access_type="c", data={
            "identifier": "workflow-shared", "title": "Workflow explicitly shared reference",
            "software": "Abaqus", "phase": [{"phase_name": "Steel"}],
        })
        shared.shared_users.add(viewer)
        hidden = JSONData.objects.create(owner=other, access_type="c", data={
            "identifier": "secret-inaccessible", "title": "Workflow SECRET inaccessible record",
            "software": "SECRET software", "relation": ["SECRET reference"],
        })
        long_name = "Long research description " * 12 + "<script>window.collectionInjection = true</script>"
        reference_ids = [public.pk, shared.pk, hidden.pk]
        for index in range(98):
            data = {
                "identifier": f"reference-{index:03}",
                "title": long_name if index == 0 else f"Reference simulation {index:03}",
                "creator": "Example researcher",
                "phase": [{"phase_name": f"Reported phase {index % 32:02}"}],
                "software_version": str(index % 3 + 1),
                "mechanical_BC": [{"loading_type": "stress", "loading_mode": "cyclic"}],
            }
            if index < 40:
                data["software"] = "DAMASK"
            elif index < 80:
                data["software"] = "Abaqus"
            if index < 40:
                data["relation"] = ["10.1234/collection.study"]
            elif index < 70:
                data["relation"] = [f"Declared reference {index}"]
            record = JSONData.objects.create(owner=viewer, data=data)
            reference_ids.append(record.pk)
        reference = ResearchCollection.objects.create(
            owner=viewer, title="Reference study with a long collection title " * 4,
            description=long_name,
        )
        reference.members.add(*reference_ids)
        unlinked = ResearchCollection.objects.create(owner=viewer, title="Metadata only study")
        unlinked.members.add(shared, record)
        empty = ResearchCollection.objects.create(owner=viewer, title="Empty research collection")
        forbidden = ResearchCollection.objects.create(owner=other, title="SECRET private collection")
        cold_collections = {}
        cold_ids = []
        temporary_ids = []
        for label in ("automatic", "native", "interrupted", "temporary"):
            records = []
            for index in range(75):
                data = {
                    "identifier": f"cold-{label}-{index}", "title": f"Cold {label} record {index}",
                    "software": "Cold summary solver", "relation": ["10.1234/cold-summary"],
                }
                records.append(JSONData(owner=viewer, data=data, size_bytes=len(json.dumps(data).encode())))
            JSONData.objects.bulk_create(records)
            cold_ids.extend(record.pk for record in records)
            if label == "temporary":
                temporary_ids = [item.pk for item in records]
            else:
                collection = ResearchCollection.objects.create(owner=viewer, title=f"Cold {label} collection")
                collection.members.add(*records)
                cold_collections[label] = reverse("collection_detail", args=[collection.pk])
        large_record = JSONData.objects.create(
            owner=viewer, data={"identifier": "cold-admin", "title": "Administrator preparation record"},
            size_bytes=17 * 1024 * 1024,
        )
        admin_collection = ResearchCollection.objects.create(owner=viewer, title="Administrator preparation collection")
        admin_collection.members.add(large_record)
        JSONData.objects.filter(pk__in=[*cold_ids, large_record.pk]).update(
            collection_summary=None, uploaded_at=timezone.now() - timedelta(days=365),
        )
        record_count = JSONData.objects.count()
        cases = {
            "home": reverse("collection_index"), "search": reverse("search"),
            "myData": reverse("json_data_list"),
            "reference": reverse("collection_detail", args=[reference.pk]),
            "unlinked": reverse("collection_detail", args=[unlinked.pk]),
            "empty": reverse("collection_detail", args=[empty.pk]),
            "forbidden": reverse("collection_detail", args=[forbidden.pk]),
            "first": first.pk, "second": second.pk, "public": public.pk,
            "shared": shared.pk, "hidden": hidden.pk,
            "ownedExtra": record.pk,
            "detail": reverse("json_data_detail", args=[first.pk]),
            "cold": cold_collections,
            "adminPreparation": reverse("collection_detail", args=[admin_collection.pk]),
        }
        self.client.force_login(viewer)
        temporary = self.client.post(reverse("graph_selection_create"), {"selected_objects": temporary_ids})
        self.assertEqual(temporary.status_code, 302)
        cold_collections["temporary"] = temporary.url
        environment = dict(
            os.environ, COLLECTION_BASE_URL=self.live_server_url,
            COLLECTION_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            COLLECTION_COOKIE_NAME=settings.SESSION_COOKIE_NAME,
            COLLECTION_CASES=json.dumps(cases),
        )
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/collections.cjs")],
            env=environment, capture_output=True, text=True, timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(JSONData.objects.count(), record_count)
        first.refresh_from_db()
        self.assertEqual(first.data, first_data)
        self.assertFalse(JSONData.objects.filter(pk__in=cold_ids, collection_summary__isnull=True).exists())
        large_record.refresh_from_db()
        self.assertIsNone(large_record.collection_summary)
        self.assertFalse(ResearchCollection.objects.filter(title="Edited workflow collection").exists())
        native = ResearchCollection.objects.get(owner=viewer, title="Native browser collection")
        self.assertEqual(set(native.members.values_list("pk", flat=True)), {second.pk, public.pk})
        print(result.stdout)
