import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import JSONData
from .upload_test_data import valid_upload_object


class AssistantFAQTests(TestCase):
    """
    Exercise local help navigation, matching and object access
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create accessible and inaccessible objects for help requests
        """
        cls.viewer = User.objects.create_user(username="faq-viewer")
        cls.owner = User.objects.create_user(username="faq-owner")
        cls.obj = JSONData.objects.create(
            owner=cls.viewer, data=valid_upload_object(identifier="faq-copper"),
        )
        cls.hidden = JSONData.objects.create(
            owner=cls.owner, data=valid_upload_object(identifier="private-marker"),
        )

    def setUp(self):
        """
        Sign in before exercising the help endpoint
        """
        self.client.force_login(self.viewer)

    def ask(self, question, **context):
        """
        Submit a real local help request

        Parameters
        ----------
        question : str
            User text or a selected question.
        **context : object
            Page and optional object reference.

        Returns
        -------
        dict
            Successful response payload.
        """
        response = self.client.post(
            reverse("fair_assistant_ask"),
            data=json.dumps({"question": question, **context}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_menu_questions_resolve_on_every_page(self):
        """
        Navigate from categories to answers without depending on the page
        """
        for page in ("search", "upload", "charts", "my-data"):
            menu = self.ask("Browse help topics", page=page)
            self.assertEqual(menu.get("topic"), "menu")
            self.assertIn("Upload help", menu["suggestions"])
            self.assertNotIn("Current object help", menu["suggestions"])
            for category in menu["suggestions"]:
                questions = self.ask(category, page=page)
                self.assertTrue(questions["suggestions"])
                for question in questions["suggestions"]:
                    answer = self.ask(question, page=page)
                    self.assertIsNotNone(answer.get("topic"), question)
                    self.assertTrue(answer["answer"], question)

    def test_typing_matches_specific_questions_in_english_and_chinese(self):
        """
        Recognize supported wording without sending every request to its page
        """
        cases = (
            ("HOW do I UPLOAD a JSON file?", "upload.start"),
            ("Why was my upload rejected?", "upload.errors"),
            ("为什么上传失败", "upload.errors"),
            ("Which required fields are missing?", "upload.required"),
            ("What if identifier already exists?", "upload.identifier"),
            ("What are the file size limits?", "upload.limits"),
            ("How should I write shared_with?", "sharing.share"),
            ("How do I find copper data?", "search.start"),
            ("How do I search by phase?", "search.start"),
            ("How do I find public data?", "search.start"),
            ("删除数据", "manage.delete"),
        )
        for question, topic in cases:
            with self.subTest(question=question):
                self.assertEqual(self.ask(question, page="detail").get("topic"), topic)

    def test_unrecognized_and_ambiguous_questions_offer_choices(self):
        """
        Avoid arbitrary answers and English substring matches
        """
        for question in ("spaceship", "unsharedness", "What is the weather?", "delete and download"):
            with self.subTest(question=question):
                reply = self.ask(question, object_id=self.obj.pk, page="detail")
                self.assertIsNone(reply.get("topic"))
                self.assertTrue(reply["suggestions"])
                self.assertNotIn("faq-copper", reply["answer"])
        ambiguous = self.ask("delete and download")
        self.assertIn("How do I delete my data?", ambiguous["suggestions"])
        self.assertIn("How do I download data?", ambiguous["suggestions"])

    def test_upload_guidance_matches_file_atomicity_and_generated_identifiers(self):
        """
        Give corrections consistent with actual upload processing
        """
        errors = self.ask("Why was my upload rejected?")
        self.assertIn("entire file", errors["answer"])
        self.assertIn("other files", errors["answer"])
        required = self.ask("Which fields are required?")
        self.assertIn("nested", required["answer"])
        self.assertIn("conditional", required["answer"])
        identifier = self.ask("How do identifiers work?")
        self.assertIn("automatically", identifier["answer"])
        self.assertIn("entire file", identifier["answer"])
        self.assertEqual(errors["links"][0]["url"], reverse("upload_json"))

    @override_settings(PILOT_MAX_UPLOAD_FILES=7, PILOT_MAX_UPLOAD_FILE_BYTES=2 * 1024**2,
                       PILOT_MAX_UPLOAD_REQUEST_BYTES=5 * 1024**2, PILOT_MAX_UPLOAD_OBJECTS=12)
    def test_limits_follow_active_settings(self):
        """
        Keep help accurate when deployment allowances change
        """
        answer = self.ask("What are the upload limits?")["answer"]
        for expected in ("7 files", "2 MiB", "5 MiB", "12 objects"):
            self.assertIn(expected, answer)

    def test_object_questions_retain_context_and_do_not_mutate_data(self):
        """
        Read approved object fields while keeping general help available
        """
        original = json.dumps(self.obj.data)
        context = {"page": "detail", "object_id": self.obj.pk}
        menu = self.ask("Browse help topics", **context)
        self.assertIn("Current object help", menu["suggestions"])
        self.assertIn("faq-copper", self.ask("Summarize this data", **context)["answer"])
        self.assertEqual(
            self.ask("What phase does this object contain?", **context)["answer"],
            "Phase information: Copper.",
        )
        self.assertEqual(self.ask("How do I upload JSON files?", **context).get("topic"), "upload.start")
        self.obj.refresh_from_db()
        self.assertEqual(json.dumps(self.obj.data), original)

    def test_object_access_is_rechecked_for_each_question(self):
        """
        Reject forged references even when asking for general help
        """
        for question in ("Browse help topics", "Summarize this data"):
            response = self.client.post(
                reverse("fair_assistant_ask"),
                data=json.dumps({"question": question, "object_id": self.hidden.pk}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("private-marker", response.content.decode())
        self.hidden.shared_users.add(self.viewer)
        self.assertIn("private-marker", self.ask("Summarize this data", object_id=self.hidden.pk)["answer"])
        self.hidden.shared_users.clear()
        response = self.client.post(
            reverse("fair_assistant_ask"),
            data=json.dumps({"question": "Summarize this data", "object_id": self.hidden.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_malformed_requests_return_actionable_errors(self):
        """
        Reject invalid request shapes instead of raising server errors
        """
        self.client.raise_request_exception = False
        for payload in ([], None, {"question": []}, {"question": {"upload": True}}):
            response = self.client.post(
                reverse("fair_assistant_ask"), data=json.dumps(payload), content_type="application/json",
            )
            self.assertEqual(response.status_code, 400, payload)

    def test_human_support_request_does_not_promise_a_handoff(self):
        """
        State support availability and offer local help topics
        """
        reply = self.ask("Can I talk to a human?")
        self.assertEqual(reply.get("topic"), "help.support")
        self.assertIn("not available", reply["answer"])
        self.assertTrue(reply["suggestions"])

    def test_whole_cube_boundary_help_preserves_tensor_meaning(self):
        """
        Describe tensor conditions without inventing scalar directions
        """
        self.obj.data["mechanical_BC"] = [{
            "vertex_list": ["V000", "V100", "V010", "V110", "V001", "V101", "V011", "V111"],
            "constraints": ["loaded"], "loading_type": "stress", "loading_mode": "static",
            "applied_load": [{"magnitude": {"xx": 1, "yy": 2, "zz": 3, "xy": 4, "xz": 5, "yz": 6}}],
        }]
        self.obj.save()
        reply = self.ask("Explain mechanical_BC", object_id=self.obj.pk)
        self.assertIn("Whole cube", reply["answer"])
        self.assertIn("tensor", reply["answer"])
        self.assertNotIn("vertex/vertices", reply["answer"])
        self.assertNotIn("X loaded", reply["answer"])
