import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from .assistant import read_context
from .assistant_knowledge import CATEGORIES, TOPICS


class AssistantCoverageTests(TestCase):
    """
    Check that expanded help is useful, reachable and faithful to the platform
    """

    def setUp(self):
        """
        Start a signed-in conversation without a current data object
        """
        self.viewer = User.objects.create_user(username="help-coverage-viewer")
        self.client.force_login(self.viewer)

    def ask(self, question, context=""):
        """
        Ask the real endpoint and verify its successful response

        Parameters
        ----------
        question : str
            Typed question or visible suggestion.
        context : str, optional
            Signed state from the preceding answer.

        Returns
        -------
        dict
            Prepared answer or clarification.
        """
        response = self.client.post(reverse("fair_assistant_ask"), data=json.dumps({
            "question": question, "context": context,
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_categories_cover_every_general_topic_in_short_pages(self):
        """
        Traverse actual menu buttons and reach all help without a long question wall
        """
        self.assertGreaterEqual(len(CATEGORIES), 9)
        reachable = set()
        for key, label in CATEGORIES.items():
            if key == "object":
                continue
            pending = [label]
            seen = set()
            while pending:
                question = pending.pop()
                if question in seen:
                    continue
                seen.add(question)
                reply = self.ask(question)
                state = read_context(reply["context"], self.viewer.pk, None)
                self.assertEqual(state["category"], key)
                self.assertLessEqual(len(state["choices"]), 6)
                self.assertLessEqual(len(reply["suggestions"]), 8)
                reachable.update(state["choices"])
                for suggestion in reply["suggestions"]:
                    answer = self.ask(suggestion)
                    if answer["topic"].startswith("menu."):
                        pending.append(suggestion)
                    else:
                        self.assertIn(answer["topic"], state["choices"])
                        self.assertTrue(answer["answer"])
                        for link in answer["links"]:
                            self.assertNotIn(resolve(link["url"]).url_name,
                                             {"home_logout", "orcid_connect", "orcid_disconnect", "json_data_delete"})
        expected = {topic["id"] for topic in TOPICS
                    if topic.get("category", topic["id"].split(".")[0]) != "object"}
        self.assertEqual(reachable, expected)

    def test_menu_page_followups_keep_the_visible_choice_order(self):
        """
        Select the sixth question and move between category pages by short replies
        """
        first = self.ask("Account help")
        state = read_context(first["context"], self.viewer.pk, None)
        sixth = self.ask("the sixth one", first["context"])
        self.assertEqual(sixth["topic"], state["choices"][5])
        second = self.ask("more", first["context"])
        next_state = read_context(second["context"], self.viewer.pk, None)
        self.assertNotEqual(state["choices"], next_state["choices"])
        previous = self.ask("back", second["context"])
        self.assertEqual(read_context(previous["context"], self.viewer.pk, None)["choices"], state["choices"])

    def test_new_questions_find_an_answer_or_a_relevant_choice(self):
        """
        Exercise user wording rather than only the catalogue's exact titles
        """
        questions = (
            ("I forgot the password for this website", {"account.recovery"}),
            ("我没收到邮件验证码", {"account.registration", "account.recovery"}),
            ("Can I attach ORCID to the login I already use?", {"account.orcid_connect"}),
            ("I signed in with ORCID but it is asking me to set a password", {"account.orcid_setup"}),
            ("I only want the files I uploaded myself", {"manage.list", "manage.filters"}),
            ("How do I stop a colleague from opening my private result?", {"sharing.revoke", "sharing.share"}),
            ("Can I turn an existing public record into a private one?", {"sharing.visibility"}),
            ("My JSON opens with a syntax error", {"upload.syntax"}),
            ("为什么一个文件有一条错误就整份不保存？", {"upload.atomicity", "upload.errors"}),
            ("How can I search from 300 to 500 kelvin?", {"search.temperature", "search.filters"}),
            ("Can I change the title of a record after uploading it?", {"manage.edit"}),
            ("Is there a recycle bin for deleted results?", {"manage.restore"}),
            ("The category counts add up to more than the total records", {"charts.counts"}),
            ("How do I save a chart as an image?", {"charts.save"}),
        )
        for question, expected in questions:
            with self.subTest(question=question):
                reply = self.ask(question)
                state = read_context(reply["context"], self.viewer.pk, None)
                candidates = [reply["topic"]] if reply["topic"] else state.get("choices", [])
                self.assertTrue(expected.intersection(candidates), reply)

    def test_answers_do_not_invent_account_or_data_management_features(self):
        """
        Preserve the current limits of recovery, sharing, editing and notifications
        """
        recovery = self.ask("How do I recover a forgotten password?")["answer"]
        self.assertIn("email password recovery", recovery)
        self.assertIn("not available", recovery)
        visibility = self.ask("Can I change public or private access after upload?")["answer"]
        self.assertIn("no public/private switch", visibility)
        edit = self.ask("Can I edit an uploaded object?")["answer"]
        self.assertIn("no editor", edit)
        history = self.ask("What does Sharing History show?")["answer"]
        self.assertIn("not the current access list", history)
        notification = self.ask("What are notifications for?")["answer"]
        self.assertIn("private", notification)
        self.assertIn("public uploads", notification)

    def test_short_revocation_followup_does_not_turn_into_sharing(self):
        """
        Keep removing access distinct from granting it in a short conversation
        """
        reply = self.ask("How do I remove someone's access to a private object?")
        self.assertEqual(reply["topic"], "sharing.revoke")
        followup = self.ask("how", reply["context"])
        self.assertEqual(followup["topic"], "sharing.revoke")

    def test_later_independent_questions_and_external_services(self):
        """
        Retain new account, export, notification and platform-scope regressions
        """
        corpus = json.loads((settings.BASE_DIR / "apps/pages/fixtures/assistant_followup_questions.json").read_text(encoding="utf-8"))
        targets = {
            "N01": {"account.profile"}, "N02": {"account.recovery", "account.registration"},
            "N03": {"sharing.history", "account.notifications"}, "N04": {"account.notifications"},
            "N05": {"manage.csv_columns"}, "N06": {"manage.formats"}, "N07": {"sharing.revoke"},
            "N08": {"search.creator", "manage.edit"},
        }
        for case in corpus["cases"]:
            with self.subTest(case=case["id"]):
                entry = case["turns"][0]
                reply = self.ask(entry["question"])
                if entry["expected"]["mode"] == "fallback":
                    self.assertIsNone(reply["topic"])
                    self.assertEqual(reply["context"], "")
                    self.assertIn("this data platform", reply["answer"])
                else:
                    state = read_context(reply["context"], self.viewer.pk, None)
                    candidates = [reply["topic"]] if reply["topic"] else state.get("choices", [])
                    self.assertTrue(targets[case["id"]].intersection(candidates), reply)

    @override_settings(PILOT_MAX_USER_JSON_BYTES=2 * 1024**3,
                       PILOT_RATE_LIMITS={"upload": {"limit": 3, "window_seconds": 120}})
    def test_quota_and_rate_guidance_use_live_settings(self):
        """
        Avoid embedding stale allowances in the expanded knowledge
        """
        self.assertIn("2 GiB", self.ask("How is my storage quota counted?")["answer"])
        rate = self.ask("Why am I asked to wait before another upload?")["answer"]
        self.assertIn("3 submissions", rate)
        self.assertIn("2 minutes", rate)
