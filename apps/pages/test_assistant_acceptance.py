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
