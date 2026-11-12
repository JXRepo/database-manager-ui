import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, CollectionRelationship, JSONData, ResearchCollection
from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class CollectionRelationshipBrowserTests(StaticLiveServerTestCase):
    """
    Exercise persisted manual graph relationships through actual desktop controls
    """

    server_thread_class = PlotLiveServerThread

    def test_drawing_editing_failures_exports_and_native_forms(self):
        """
        Draw and revise relationships without changing uploaded records

        A small collection supports direct drawing while a larger collection
        checks links whose endpoints fall on different member pages.
        """
        self.assertTrue(shutil.which("node"), "Relationship browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="manual-relation-viewer")
        other = User.objects.create_user(username="manual-relation-other")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        records = []
        for index in range(31):
            data = {
                "identifier": f"manual-browser-{index}",
                "title": f"Simulation {index:02} " + ("long descriptive name " * 8 if index == 2 else ""),
                "software": "Recorded solver", "phase": [{"phase_name": "Copper"}],
                "relation": ["10.1234/source-reference"],
                "stress": {"xx": [0, 1.23456789]},
            }
            records.append(JSONData.objects.create(owner=viewer, data=data))
        hidden = JSONData.objects.create(owner=other, access_type="c", data={
            "identifier": "SECRET-relation-member", "title": "SECRET unavailable record",
        })
        small = ResearchCollection.objects.create(owner=viewer, title="Manual relationship study")
        small.members.add(*records[:3], hidden)
        large = ResearchCollection.objects.create(owner=viewer, title="Relationships across member pages")
        large.members.add(*records, hidden)
        parallel = ResearchCollection.objects.create(owner=viewer, title="Distinct relationships between the same objects")
        parallel.members.add(*records[:2])
        parallel_links = []
        for index in range(13):
            parallel_links.append(CollectionRelationship.objects.create(
                collection=parallel, source=records[0], target=records[1], label=f"Parallel relationship {index + 1}",
            ))
        original_data = dict(JSONData.objects.values_list("pk", "data"))
        self.client.force_login(viewer)
        temporary = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [records[0].pk, records[1].pk],
        })
        self.assertEqual(temporary.status_code, 302)
        cases = {
            "small": reverse("collection_detail", args=[small.pk]),
            "large": reverse("collection_detail", args=[large.pk]),
            "temporary": temporary.url,
            "parallel": reverse("collection_detail", args=[parallel.pk]),
            "parallel_ids": [link.pk for link in parallel_links],
            "first": records[0].pk, "second": records[1].pk,
            "third": records[2].pk, "distant": records[-1].pk,
            "hidden": hidden.pk,
        }
        environment = dict(
            os.environ, MANUAL_GRAPH_BASE_URL=self.live_server_url,
            MANUAL_GRAPH_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            MANUAL_GRAPH_COOKIE_NAME=settings.SESSION_COOKIE_NAME,
            MANUAL_GRAPH_CASES=json.dumps(cases),
        )
        result = subprocess.run(
            [shutil.which("node"), str(settings.BASE_DIR / "tests/browser/collection-relationships.cjs")],
            env=environment, capture_output=True, text=True, timeout=240, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(dict(JSONData.objects.values_list("pk", "data")), original_data)
        native = CollectionRelationship.objects.get(collection=small, label="Native recorded relationship")
        self.assertEqual((native.source_id, native.target_id), (records[0].pk, records[1].pk))
        across_pages = CollectionRelationship.objects.get(collection=large, label="Related across member pages")
        self.assertEqual((across_pages.source_id, across_pages.target_id), (records[-1].pk, records[0].pk))
        self.assertEqual(CollectionRelationship.objects.count(), 15)
        print(result.stdout)
