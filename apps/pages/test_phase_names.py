import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class PhaseNameTests(TestCase):
    """
    Verify canonical phase names without changing stored data or legacy searches
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create users for accessible and private phase metadata
        """
        cls.viewer = User.objects.create_user(username="phase-name-viewer")
        cls.other = User.objects.create_user(username="phase-name-other")

    def setUp(self):
        """
        Sign in before using search and the assistant
        """
        self.client.force_login(self.viewer)

    def test_assistant_prefers_canonical_names_in_arrays_and_objects(self):
        """
        Answer phase questions using canonical names with legacy fallbacks
        """
        cases = (
            ([{"phase_name": "Copper"}], "Copper"),
            ({"phase_name": "Nickel"}, "Nickel"),
            ([{
                "phase_name": "Iron", "phase_identifier": "Historical Iron",
                "name": "Generic Iron", "identifier": "internal-iron",
            }], "Iron"),
            ({
                "phase_name": "Silver", "phase_identifier": "Historical Silver",
                "name": "Generic Silver", "identifier": "internal-silver",
            }, "Silver"),
            ([{"phase_identifier": "Legacy Copper"}], "Legacy Copper"),
            ({"name": "Legacy Nickel"}, "Legacy Nickel"),
            ([{"phase_name": "", "phase_identifier": "Legacy Tin"}], "Legacy Tin"),
            ([{"phase_name": " \t ", "phase_identifier": "Legacy Lead"}], "Legacy Lead"),
            ([{"phase_name": "Copper"}, {"phase_identifier": "Tin"}], "Copper, Tin"),
            ("Legacy Zinc", "Legacy Zinc"),
        )
        for phase, expected in cases:
            with self.subTest(phase=phase):
                data = {"identifier": "phase-answer", "phase": phase}
                obj = JSONData.objects.create(owner=self.viewer, data=data)
                response = self.client.post(
                    reverse("fair_assistant_ask"),
                    data=json.dumps({
                        "page": "detail", "object_id": obj.pk,
                        "question": "What phase does this object contain?",
                    }),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["answer"], f"Phase information: {expected}.")
                obj.refresh_from_db()
                self.assertEqual(json.dumps(obj.data), json.dumps(data))

    def test_common_phase_search_combines_canonical_and_legacy_text(self):
        """
        Find canonical phase names alongside generic labels using complete words
        """
        phases = {
            "canonical-only": [{"phase_name": "Copper phase"}],
            "canonical-with-aliases": [{
                "phase_name": "Nickel phase", "phase_identifier": "Historical Nickel",
                "name": "Legacy display", "identifier": "legacy-key",
            }],
            "canonical-dict": {"phase_name": "Iron phase", "name": "Generic label"},
            "canonical-with-legacy": [{
                "phase_name": "Platinum phase", "phase_identifier": "Historical Platinum",
            }],
            "partial-word": [{"phase_name": "NickelAlloy phase"}],
            "legacy": [{"phase_identifier": "Tin phase"}],
        }
        objects = {
            key: JSONData.objects.create(owner=self.viewer, data={"identifier": key, "phase": phase})
            for key, phase in phases.items()
        }
        JSONData.objects.create(
            owner=self.other,
            access_type="c",
            data={"identifier": "hidden-phase", "phase": phases["canonical-with-aliases"]},
        )
        cases = (
            ("PHASE copper", "canonical-only"),
            (" PHASE\tNICKEL ", "canonical-with-aliases"),
            ("phase iron", "canonical-dict"),
            ("phase platinum", "canonical-with-legacy"),
            ("Historical Platinum", "canonical-with-legacy"),
            ("NickelAlloy phase", "partial-word"),
            ("phase tin", "legacy"),
            ("DISPLAY legacy", "canonical-with-aliases"),
            ("legacy-key", "canonical-with-aliases"),
            ("nickel missing", None),
        )
        for query, key in cases:
            with self.subTest(query=query):
                response = self.client.get(reverse("search"), {"phase": query})

                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["search_errors"])
                self.assertEqual(
                    [obj.pk for obj in response.context["data_objects"]],
                    [objects[key].pk] if key else [],
                )
        for key, obj in objects.items():
            obj.refresh_from_db()
            self.assertEqual(obj.data, {"identifier": key, "phase": phases[key]})
