import json
import tempfile
import time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .assistant import read_context
from .models import JSONData
from .upload_test_data import valid_upload_object


class AssistantDialogueTests(TestCase):
    """
    Check useful clarification and conversation through the actual endpoint
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create a viewer and an initially shared object
        """
        cls.viewer = User.objects.create_user(username="dialogue-viewer")
        owner = User.objects.create_user(username="dialogue-owner")
        cls.obj = JSONData.objects.create(owner=owner, data=valid_upload_object(identifier="dialogue-private"))
        cls.obj.shared_users.add(cls.viewer)

    def setUp(self):
        """
        Start an independent signed-in conversation
        """
        self.client.force_login(self.viewer)

    def ask(self, question, **context):
        """
        Send a question with optional conversation or object context

        Parameters
        ----------
        question : str
            User wording.
        **context : object
            Extra request fields.

        Returns
        -------
        dict
            Successful help response.
        """
        response = self.client.post(reverse("fair_assistant_ask"),
            data=json.dumps({"question": question, **context}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_data_form_clarifies_then_accepts_a_short_follow_up(self):
        """
        Resolve the user's actual failed question without requiring exact buttons
        """
        first = self.ask("data form")
        self.assertIsNone(first["topic"])
        self.assertIn("JSON format", first["suggestions"])
        self.assertIn("Upload form", first["suggestions"])
        second = self.ask("format", context=first["context"])
        self.assertEqual(second["topic"], "upload.format")
        self.assertIn("JSON", second["answer"])
        third = self.ask("which fields?", context=second["context"])
        self.assertEqual(third["topic"], "upload.required")
        self.assertIn("phase", third["answer"])
        self.assertIn("creator", third["answer"])

    def test_numbered_choice_and_topic_change(self):
        """
        Honor choice order and let a new full question replace the topic
        """
        first = self.ask("data form")
        second = self.ask("the second one", context=first["context"])
        self.assertEqual(second["topic"], "upload.start")
        third = self.ask("I want to erase my old simulations", context=second["context"])
        self.assertEqual(third["topic"], "manage.delete")

    def test_semantic_questions_work_without_matching_literal_patterns(self):
        """
        Map ordinary paraphrases and Chinese questions to grounded answers
        """
        for question, expected in (
            ("My file will not go through", "upload.errors"),
            ("I want to erase my old simulations", "manage.delete"),
            ("What file layout does the platform expect?", "upload.format"),
        ):
            with self.subTest(question=question):
                self.assertEqual(self.ask(question)["topic"], expected)

    def test_privacy_question_can_distinguish_access_from_revocation(self):
        """
        Offer the relevant next step when a privacy request leaves intent open
        """
        reply = self.ask("我不想让别人看到我的结果")
        if reply["topic"]:
            self.assertEqual(reply["topic"], "sharing.access")
        else:
            state = read_context(reply["context"], self.viewer.pk, None)
            self.assertIn("sharing.access", state["choices"])
            self.assertIn("sharing.revoke", state["choices"])

    def test_unrelated_question_never_inherits_the_last_answer(self):
        """
        Keep unrelated conversation out of data context and temperature filters
        """
        first = self.ask("Summarize this data", object_id=self.obj.pk)
        reply = self.ask("weather tomorrow", object_id=self.obj.pk, context=first["context"])
        self.assertIsNone(reply["topic"])
        self.assertNotIn("dialogue-private", reply["answer"])
        self.assertNotIn("kelvin", reply["answer"])

    def test_context_does_not_replace_access_checks(self):
        """
        Revoke object access between turns and reject the old conversation
        """
        first = self.ask("Summarize this data", object_id=self.obj.pk)
        self.obj.shared_users.clear()
        response = self.client.post(reverse("fair_assistant_ask"), data=json.dumps({
            "question": "and the software?", "object_id": self.obj.pk, "context": first["context"],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("dialogue-private", response.content.decode())

    def test_invalid_context_and_menu_reset_are_safe(self):
        """
        Ignore forged state and clear conversation when browsing all topics
        """
        invalid = self.ask("the second one", context="forged-context")
        self.assertIsNone(invalid["topic"])
        first = self.ask("data form")
        menu = self.ask("Browse help topics", context=first["context"])
        self.assertEqual(menu["topic"], "menu")
        self.assertEqual(menu["context"], "")

    def test_context_expires_and_cannot_move_between_users_or_objects(self):
        """
        Reject old or transferred choices without preventing a fresh question
        """
        first = self.ask("data form")
        other = User.objects.create_user(username="different-dialogue-viewer")
        self.client.force_login(other)
        self.assertIsNone(self.ask("the second one", context=first["context"])["topic"])
        self.client.force_login(self.viewer)
        self.assertIsNone(self.ask("the second one", object_id=self.obj.pk, context=first["context"])["topic"])
        with patch("django.core.signing.time.time", return_value=time.time() - 1801):
            expired = self.ask("data form")
        self.assertIsNone(self.ask("the second one", context=expired["context"])["topic"])

    def test_model_failure_keeps_exact_help_and_object_summaries(self):
        """
        Retain useful choices and authorized facts when semantic matching fails
        """
        with tempfile.TemporaryDirectory() as directory, override_settings(ASSISTANT_MODEL_DIR=directory):
            reply = self.ask("Where should I put the file I prepared?")
            self.assertIn("temporarily unavailable", reply["answer"])
            self.assertIn("Upload help", reply["suggestions"])
            self.assertEqual(self.ask("Required fields")["topic"], "upload.required")
            summary = self.ask("Summarize this data", object_id=self.obj.pk)
            self.assertIn("dialogue-private", summary["answer"])
        with patch("apps.pages.assistant_semantics._Encoder.encode", side_effect=RuntimeError("CPU session failed")):
            reply = self.ask("Where should I put the file I prepared?")
            self.assertIn("temporarily unavailable", reply["answer"])

    def test_malformed_conversation_is_rejected(self):
        """
        Reject oversized and nontext context before model work
        """
        for token in ({"topic": "upload.start"}, "x" * 4097):
            with self.subTest(token_type=type(token).__name__):
                response = self.client.post(reverse("fair_assistant_ask"), data=json.dumps({
                    "question": "the second one", "context": token,
                }), content_type="application/json")
                self.assertEqual(response.status_code, 400)
