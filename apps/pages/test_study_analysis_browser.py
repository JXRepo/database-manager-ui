"""
Exercise named analyses and detailed difference navigation in desktop Chromium.
"""

import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db.models import TextField
from django.db.models.functions import Cast, MD5
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountProfile, JSONData, ResearchCollection, SavedStudyAnalysis
from .test_plot_browser import PlotLiveServerThread


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class StudyAnalysisBrowserTests(StaticLiveServerTestCase):
    """
    Follow a complete private analysis through native and enhanced controls.
    """

    server_thread_class = PlotLiveServerThread

    def test_saved_analysis_and_difference_navigation(self):
        """
        Save visible choices, locate differences and preserve revisions and notes.

        Synthetic saved views include changed and inaccessible sources so browser
        checks cover the same evidence and access boundaries as ordinary studies.
        """
        self.assertTrue(shutil.which("node"), "Study browser checks require Node")
        self.assertTrue(Path(os.environ.get("CHROMIUM_BIN", "/usr/bin/chromium")).is_file())
        viewer = User.objects.create_user(username="analysis-browser")
        other = User.objects.create_user(username="analysis-other")
        AccountProfile.objects.create(user=viewer, getting_started_dismissed_at=timezone.now())
        collection = ResearchCollection.objects.create(owner=viewer, title="Copper analysis workspace")
        template = {
            "software": "DAMASK", "global_temperature": 298, "discretization_count": 100,
            "units": {"Temperature": "K", "Stress": "MPa", "Strain": "1"},
            "phase": [{"phase_name": "Copper", "constitutive_model": {
                "elastic_model_name": "Anisotropic elasticity",
                "elastic_parameters": {"C11": "210.000000000000000001", "C12": 0},
                "plastic_parameters": {"active": False}, "units": {"C11": "GPa"},
            }}],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "cyclic",
                               "stress_tensor": {"stress_11": [0, 10, -3]}, "recorded_step": 0}],
            "stress": {"equivalent_stress": [0, 20.123456789, 38]},
            "total_strain": {"equivalent_strain": [0, .001, .002]},
        }
        for index in range(35):
            template["phase"][0]["constitutive_model"]["plastic_parameters"][f"recorded_coefficient_{index}"] = index
        records = []
        for index, title in enumerate(("Reference copper response", "Changed model and loading",
                                       "Incomplete parameter record", "Fourth copper response")):
            data = deepcopy(template)
            data.update(identifier=f"analysis-{index}", title=title)
            if index == 1:
                data["global_temperature"] = 323
                data["phase"][0]["constitutive_model"]["elastic_parameters"]["C11"] = "220.000000000000000002"
                data["mechanical_BC"][0]["stress_tensor"]["stress_11"] = [0, 12, -4]
            elif index == 2:
                del data["phase"][0]["constitutive_model"]["plastic_parameters"]["active"]
            record = JSONData.objects.create(owner=viewer, data=data)
            records.append(record)
        hidden = JSONData.objects.create(owner=other, data={"title": "SECRET forbidden source", "identifier": "SECRET-id"})
        collection.members.add(*records, hidden)
        digests = dict(JSONData.objects.filter(pk__in=[item.pk for item in records]).annotate(
            digest=MD5(Cast("data", TextField())),
        ).values_list("pk", "digest"))
        state = {"links": "members", "panel": "compare", "compare": f"{records[0].pk},{records[1].pk}", "inspect": "1"}
        changed = SavedStudyAnalysis.objects.create(
            collection=collection, title="Earlier saved source values", state=state,
            notes="Keep this original observation.",
            source_digests={str(pk): value for pk, value in digests.items() if pk in (records[0].pk, records[1].pk)},
        )
        records[1].data["revision_note"] = "Source changed after the analysis was saved"
        records[1].save(update_fields=["data"])
        unavailable = SavedStudyAnalysis.objects.create(
            collection=collection, title="Unavailable source analysis", notes="A private saved observation.",
            state={**state, "compare": f"{records[0].pk},{hidden.pk}"}, source_digests={},
        )
        for index in range(13):
            SavedStudyAnalysis.objects.create(collection=collection, title=f"Previous analysis {index:02}", state=state,
                                             source_digests={str(records[0].pk): digests[records[0].pk]})
        original = dict(JSONData.objects.values_list("pk", "data"))
        self.client.force_login(viewer)
        temporary = self.client.post(reverse("graph_selection_create"), {"selected_objects": [records[0].pk, records[1].pk]})
        self.assertEqual(temporary.status_code, 302)
        cases = {
            "collection": reverse("collection_detail", args=[collection.pk]),
            "temporary": temporary.url, "records": [item.pk for item in records],
            "changedOpen": reverse("collection_analysis_open", args=[collection.pk, changed.pk]),
            "unavailableOpen": reverse("collection_analysis_open", args=[collection.pk, unavailable.pk]),
        }
        environment = dict(os.environ, STUDY_BASE_URL=self.live_server_url,
                           STUDY_SESSION=self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                           STUDY_COOKIE_NAME=settings.SESSION_COOKIE_NAME, STUDY_CASES=json.dumps(cases))
        result = subprocess.run([shutil.which("node"), str(settings.BASE_DIR / "tests/browser/study-analysis.cjs")],
                                env=environment, capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(dict(JSONData.objects.values_list("pk", "data")), original)
        self.assertEqual(collection.members.count(), len(records) + 1)
        analysis = SavedStudyAnalysis.objects.get(collection=collection, title="Copper temperature review")
        self.assertEqual(analysis.notes, "Updated observation: compare the supplied values.")
        self.assertEqual(analysis.state["curve_view"], "overlay")
        self.assertEqual(analysis.state["detail_q"], "C11")
        self.assertEqual(analysis.state["detail_status"], "different")
        self.assertEqual(analysis.state["compare"], ",".join(str(item.pk) for item in records))
        self.assertFalse(SavedStudyAnalysis.objects.filter(collection=collection, title="Copied review").exists())
        self.assertTrue(SavedStudyAnalysis.objects.filter(collection=collection, title="Native saved review").exists())
        changed.refresh_from_db()
        self.assertEqual(changed.notes, "Keep this original observation.")
        self.assertEqual(changed.revision, 1)
        print(result.stdout)
