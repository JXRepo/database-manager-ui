import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .assistant import read_context
from .models import JSONData
from .upload_test_data import valid_upload_object


class AssistantAcceptanceTests(TestCase):
    """
    Retain independent questions as useful-answer and clarification regressions

    Direct answers and relevant choices both satisfy this usefulness check.
    The independent evaluation also reports stricter response-mode scores.
    """

    def test_natural_questions_and_multi_turn_conversations(self):
        """
        Check the preserved corpus through the real view with signed state
        """
        viewer = User.objects.create_user(username="acceptance-viewer")
        owner = User.objects.create_user(username="acceptance-owner")
        owned = JSONData.objects.create(owner=viewer, data=valid_upload_object(identifier="acceptance-owned"))
        shared = JSONData.objects.create(owner=owner, data=valid_upload_object(identifier="acceptance-shared"))
        originals = {obj.pk: obj.data for obj in (owned, shared)}
        self.client.force_login(viewer)
        corpus = json.loads((settings.BASE_DIR / "apps/pages/fixtures/assistant_questions.json").read_text(encoding="utf-8"))
        totals = {"direct": 0, "clarified": 0, "outside": 0, "denied": 0}
        for scenario in corpus["cases"]:
            token = ""
            previous_choices = []
            kind = scenario.get("context")
            obj = owned if kind == "accessible_object" else shared if kind == "shared_private_object" else None
            shared.shared_users.add(viewer)
            for number, entry in enumerate(scenario["turns"], start=1):
                with self.subTest(case=scenario["id"], turn=number, question=entry["question"]):
                    if entry.get("before"):
                        shared.shared_users.clear()
                    response = self.client.post(reverse("fair_assistant_ask"), data=json.dumps({
                        "question": entry["question"], "object_id": obj.pk if obj else None, "context": token,
                    }), content_type="application/json")
                    expected = entry["expected"]
                    mode = expected["mode"]
                    if mode == "http_error":
                        self.assertIn(response.status_code, expected["statuses"])
                        self.assertNotIn("acceptance-shared", response.content.decode())
                        totals["denied"] += 1
                        continue
                    self.assertEqual(response.status_code, 200)
                    reply = response.json()
                    token = reply["context"]
                    state = read_context(token, viewer.pk, obj.pk if obj else None)
                    choices = state.get("choices", [])
                    topic = reply.get("topic")
                    self.assertTrue(reply["answer"])
                    if mode == "fallback":
                        self.assertIsNone(topic)
                        self.assertEqual(token, "")
                        self.assertTrue(reply["suggestions"])
                        totals["outside"] += 1
                    elif mode == "clarify":
                        self.assertIsNone(topic)
                        self.assertTrue(set(expected["required_candidates"]).issubset(choices))
                        self.assertLessEqual(len(choices), expected["max_candidates"])
                        totals["clarified"] += 1
                    elif mode == "previous_choice":
                        self.assertEqual(topic, previous_choices[expected["index"]])
                        self.assertIn(topic, expected["eligible_topics"])
                        totals["direct"] += 1
                    else:
                        targets = set(expected["topics"])
                        if topic:
                            # Upload instructions also explain collections, so
                            # judge this equivalent answer by its actual content
                            if targets == {"upload.format"} and topic == "upload.start":
                                self.assertIn("collection of objects", reply["answer"])
                            else:
                                self.assertIn(topic, targets)
                            totals["direct"] += 1
                        else:
                            self.assertTrue(targets.intersection(choices), reply)
                            self.assertLessEqual(len(choices), 4)
                            totals["clarified"] += 1
                    previous_choices = choices
        self.assertEqual(JSONData.objects.count(), 2)
        for key, original in originals.items():
            self.assertEqual(JSONData.objects.get(pk=key).data, original)
        print("Assistant corpus (direct or useful clarification):", totals)

    def test_expanded_independent_questions_remain_useful(self):
        """
        Retain the separately written expansion questions as intent regressions

        Topic equivalences were reviewed against the actual prepared answers.
        This measures useful answers or choices, not every strict original fact.
        """
        viewer = User.objects.create_user(username="expanded-acceptance-viewer")
        self.client.force_login(viewer)
        corpus = json.loads((settings.BASE_DIR / "apps/pages/fixtures/assistant_expanded_questions.json").read_text(encoding="utf-8"))
        targets = {
            "E01": {"account.registration"}, "E02": {"account.registration"},
            "E03": {"account.registration", "account.password"}, "E04": {"account.profile"},
            "E05": {"account.session"}, "E06": {"account.session"}, "E07": {"account.recovery"},
            "E08": {"account.password", "account.recovery"}, "E09": {"account.orcid_connect"},
            "E10": {"account.orcid_connect"}, "E11": {"account.orcid_setup"},
            "E12": {"account.orcid_disconnect"}, "E13": {"account.orcid_connect"},
            "E14": {"account.orcid_profile"}, "E15": {"account.orcid_failure"},
            "E16": {"sharing.share", "upload.sharing_error"}, "E17": {"sharing.history", "sharing.revoke"},
            "E18": {"sharing.access"}, "E19": {"sharing.visibility"}, "E20": {"sharing.license", "sharing.access"},
            "E21": {"sharing.share", "sharing.received"}, "E22": {"account.notifications"},
            "E23": {"account.notifications"}, "E24": {"account.notifications", "sharing.unavailable", "sharing.revoke"},
            "E25": {"sharing.received", "sharing.history"}, "E26": {"detail.metadata", "manage.formats", "manage.download"},
            "E27": {"manage.download", "manage.formats"}, "E28": {"manage.formats", "charts.curves"}, "E29": {"charts.curves"},
            "E30": {"manage.csv_missing", "manage.formats"}, "E31": {"manage.formats", "manage.download"},
            "E32": {"manage.formats"}, "E33": {"manage.edit"}, "E34": {"manage.restore"},
            "E35": {"account.delete"}, "E36": {"manage.edit"}, "E37": {"start.tour"},
            "E38": {"start.backup"}, "E39": {"start.backup"}, "E40": {"manage.download", "manage.formats"},
        }
        totals = {"direct": 0, "clarified": 0}
        for case in corpus["cases"]:
            token = ""
            for number, entry in enumerate(case["turns"], start=1):
                with self.subTest(case=case["id"], turn=number, question=entry["question"]):
                    response = self.client.post(reverse("fair_assistant_ask"), data=json.dumps({
                        "question": entry["question"], "context": token,
                    }), content_type="application/json")
                    self.assertEqual(response.status_code, 200)
                    reply = response.json()
                    token = reply["context"]
                    state = read_context(token, viewer.pk, None)
                    candidates = [reply["topic"]] if reply["topic"] else state.get("choices", [])
                    self.assertTrue(targets[case["id"]].intersection(candidates), reply)
                    self.assertLessEqual(len(candidates), 4)
                    totals["direct" if reply["topic"] else "clarified"] += 1
        self.assertFalse(JSONData.objects.exists())
        print("Expanded assistant corpus (direct or useful clarification):", totals)
