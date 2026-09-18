import copy
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.html import parse_html
from django.urls import reverse
from django.utils.html import escape

from .models import JSONData


def _elements(element):
    """
    Traverse parsed HTML elements in document order

    Parameters
    ----------
    element : django.test.html.Element or str
        Parsed node to inspect.

    Yields
    ------
    django.test.html.Element
        The node and its element descendants.
    """
    if isinstance(element, str):
        return
    yield element
    for child in element.children:
        yield from _elements(child)


def _marked(element, attribute):
    """
    Find report nodes carrying a semantic data attribute

    Parameters
    ----------
    element : django.test.html.Element
        Root of the report subtree.
    attribute : str
        Marker used by the upload report.

    Returns
    -------
    list
        Matching nodes in document order.
    """
    return [node for node in _elements(element) if attribute in dict(node.attributes)]


def _text(element, header_only=False):
    """
    Read visible report text without relying on heading markup

    Parameters
    ----------
    element : django.test.html.Element or str
        Parsed node to read.
    header_only : bool, optional
        Exclude category sections when checking an object heading.

    Returns
    -------
    str
        Text content with whitespace between child nodes.
    """
    if isinstance(element, str):
        return element
    if header_only and "data-upload-category" in dict(element.attributes):
        return ""
    return " ".join(_text(child, header_only) for child in element.children).strip()


class UploadFeedbackTests(TestCase):
    """
    Verify grouped upload feedback through redirects and rendered HTML
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create isolated owners and a complete minimal upload object
        """
        cls.owner = User.objects.create_user(username="feedback-owner")
        cls.other = User.objects.create_user(username="feedback-other")
        cls.example = {
            "title": "Title", "creator": "Creator", "creator_affiliation": "Affiliation",
            "date": "2026-09-18", "shared_with": [{"access_type": "c"}],
            "rights": "Rights", "rights_holder": "Rights holder", "software": "Software",
            "software_version": "1", "system": "System", "system_version": "1",
            "processor_specifications": "Processor", "input_path": "input", "results_path": "results",
            "RVE_size": "size", "RVE_continuity": True, "discretization_type": "type",
            "discretization_unit_size": "unit", "discretization_count": 1,
            "mechanical_BC": "boundary", "phase": "phase", "stress": "stress",
            "total_strain": "strain", "units": "units",
        }

    def setUp(self):
        """
        Authenticate the uploader without real account credentials
        """
        self.client.force_login(self.owner)

    def _data(self, title, identifier=None):
        """
        Prepare an independent valid object with an optional supplied identifier

        Parameters
        ----------
        title : str
            Distinct object title.
        identifier : object, optional
            Supplied identifier to validate, omitted when None.

        Returns
        -------
        dict
            Complete object ready for targeted validation changes.
        """
        data = copy.deepcopy(self.example)
        data["title"] = title
        if identifier is not None:
            data["identifier"] = identifier
        return data

    def _upload(self, *files):
        """
        Submit named files and follow the normal upload redirect

        Parameters
        ----------
        files : tuple
            Pairs of filename and JSON payload in submission order.

        Returns
        -------
        HttpResponse
            Upload page reached by GET after submission.
        """
        uploaded = []
        for name, payload in files:
            uploaded.append(SimpleUploadedFile(
                name, json.dumps(payload).encode("utf-8"), content_type="application/json",
            ))
        response = self.client.post(reverse("upload_json"), {"file": uploaded}, follow=True)
        self.assertEqual(response.redirect_chain, [(reverse("upload_json"), 302)])
        self.assertEqual(response.wsgi_request.method, "GET")
        return response

    def _report(self, response):
        """
        Require one actual HTML report after message storage and redirect

        Parameters
        ----------
        response : HttpResponse
            Rendered upload page.

        Returns
        -------
        django.test.html.Element
            The single grouped upload report.
        """
        reports = _marked(parse_html(response.content.decode()), "data-upload-report")
        self.assertEqual(len(reports), 1)
        return reports[0]

    def test_mixed_files_preserve_order_and_stop_after_the_failed_file(self):
        """
        Keep earlier uploads and report failed objects before later unprocessed files
        """
        first = self._data("First invalid object", "first-invalid")
        first.pop("phase")
        second = self._data("Second invalid object", "second-invalid")
        second["software"] = ""
        third = self._data("Third invalid object", "third-invalid")
        third.pop("creator")
        saved = self._data("Saved from first file", "first-saved")
        response = self._upload(
            ("z-first.json", saved),
            ("a-second.json", [self._data("Unstored valid neighbor"), first, second]),
            ("third.json", [third, self._data("Unprocessed valid object", " ")]),
        )
        self.assertEqual(JSONData.objects.count(), 1)
        self.assertEqual(JSONData.objects.get().data, saved)
        self.assertNotContains(response, "partially successful")
        files = _marked(self._report(response), "data-upload-file")
        self.assertEqual(len(files), 3)
        self.assertIn("z-first.json", _text(files[0]))
        self.assertIn("a-second.json", _text(files[1]))
        self.assertIn("third.json", _text(files[2]))
        self.assertFalse(_marked(files[0], "data-upload-object"))
        failed_objects = _marked(files[1], "data-upload-object")
        self.assertEqual(len(failed_objects), 2)
        self.assertFalse(_marked(files[2], "data-upload-object"))
        self.assertFalse(_marked(files[2], "data-upload-category"))
        self.assertIn("Not uploaded", _text(files[2]))
        self.assertNotIn("Third invalid object", _text(files[2]))
        for node, title, identifier, position in [
            (failed_objects[0], "First invalid object", "first-invalid", 2),
            (failed_objects[1], "Second invalid object", "second-invalid", 3),
        ]:
            header = _text(node, header_only=True)
            self.assertLess(header.index(title), header.index(identifier))
            self.assertRegex(header.casefold(), rf"object\s+{position}\b")

    def test_file_and_object_structure_errors_keep_their_own_location_and_guidance(self):
        """
        Distinguish JSON syntax and root structure errors from invalid list entries
        """
        files = [
            SimpleUploadedFile("syntax.json", b'{"title":', content_type="application/json"),
            SimpleUploadedFile("root.json", b"42", content_type="application/json"),
            SimpleUploadedFile(
                "entries.json", json.dumps([self._data("Valid neighbor"), False]).encode("utf-8"),
                content_type="application/json",
            ),
        ]
        guidance = []
        for index, uploaded_file in enumerate(files):
            with self.subTest(filename=uploaded_file.name):
                response = self.client.post(reverse("upload_json"), {"file": uploaded_file}, follow=True)
                self.assertEqual(response.redirect_chain, [(reverse("upload_json"), 302)])
                self.assertEqual(JSONData.objects.count(), 0)
                reports = _marked(self._report(response), "data-upload-file")
                self.assertEqual(len(reports), 1)
                file_report = reports[0]
                self.assertIn(uploaded_file.name, _text(file_report))
                objects = _marked(file_report, "data-upload-object")
                if index < 2:
                    self.assertFalse(objects)
                else:
                    self.assertEqual(len(objects), 1)
                    self.assertRegex(_text(objects[0], header_only=True).casefold(), r"object\s+2\b")
                groups = _marked(file_report, "data-upload-category")
                self.assertEqual(len(groups), 1)
                expected_category = "invalid_file" if index == 0 else "invalid_structure"
                self.assertEqual(dict(groups[0].attributes)["data-upload-category"], expected_category)
                guidance.append(_text(_marked(groups[0], "data-upload-guidance")[0]))
        self.assertIn("syntax", guidance[0].casefold())
        self.assertIn("list", guidance[1].casefold())
        self.assertIn("entry", guidance[2].casefold())
        self.assertIn("JSON object", guidance[2])
        self.assertNotIn("list of objects", guidance[2])
        self.assertEqual(len(set(guidance)), 3)

    def test_sharing_errors_offer_only_guidance_for_the_selected_problem(self):
        """
        Separate malformed sharing entries from access values and public usernames
        """
        malformed = self._data("Malformed sharing entry", "malformed-sharing")
        malformed["shared_with"] = ["invalid entry"]
        invalid_access = self._data("Invalid access value", "invalid-access")
        invalid_access["shared_with"] = [{"access_type": "private"}]
        public_username = self._data("Public object with username", "public-username")
        public_username["shared_with"] = [{"access_type": "all", "username": "some-user"}]
        response = self._upload(("sharing.json", [malformed, invalid_access, public_username]))
        self.assertEqual(JSONData.objects.count(), 0)
        objects = _marked(self._report(response), "data-upload-object")
        self.assertEqual(len(objects), 3)
        guidance = []
        for node, expected in zip(objects, ["invalid_share_structure", "invalid_access", "public_share_username"]):
            groups = _marked(node, "data-upload-category")
            self.assertEqual(len(groups), 1)
            self.assertEqual(dict(groups[0].attributes)["data-upload-category"], expected)
            guidance.append(_text(_marked(groups[0], "data-upload-guidance")[0]))
        self.assertIn("JSON object", guidance[0])
        self.assertIn('"all"', guidance[1])
        self.assertIn('"c"', guidance[1])
        self.assertNotIn("Remove username", guidance[1])
        self.assertIn("Remove username", guidance[2])
        self.assertNotIn("JSON object", guidance[2])
        self.assertEqual(len(set(guidance)), 3)

    def test_missing_empty_and_identifier_errors_have_separate_fields_and_guidance(self):
        """
        Report all independent validation categories for the same failed object
        """
        data = self._data("Several independent issues", 123)
        data.pop("creator")
        data.pop("phase")
        data["software"] = ""
        data["rights"] = []
        response = self._upload(("categories.json", data))
        self.assertEqual(JSONData.objects.count(), 0)
        objects = _marked(self._report(response), "data-upload-object")
        self.assertEqual(len(objects), 1)
        sections = _marked(objects[0], "data-upload-category")
        categories = [dict(section.attributes)["data-upload-category"] for section in sections]
        self.assertEqual(categories, ["missing_required", "empty_values", "invalid_identifier"])
        guidance_text = []
        for section, fields in zip(sections[:2], [("creator", "phase"), ("software", "rights")]):
            lists = [node for node in _elements(section) if node.name == "ol"]
            self.assertEqual(len(lists), 1)
            field_text = _text(lists[0])
            for field in fields:
                self.assertIn(field, field_text)
            other_fields = ("software", "rights") if fields[0] == "creator" else ("creator", "phase")
            for field in other_fields:
                self.assertNotIn(field, field_text)
        for section in sections:
            nodes = list(_elements(section))
            lists = [node for node in nodes if node.name == "ol"]
            self.assertEqual(len(lists), 1)
            self.assertTrue(any(node.name == "li" for node in _elements(lists[0])))
            guidance = _marked(section, "data-upload-guidance")
            self.assertEqual(len(guidance), 1)
            self.assertEqual(guidance[0].name, "p")
            self.assertTrue(_text(guidance[0]).strip())
            self.assertLess(nodes.index(lists[0]), nodes.index(guidance[0]))
            guidance_text.append(_text(guidance[0]))
        self.assertEqual(len(set(guidance_text)), 3)

    def test_identifier_errors_do_not_create_labels_for_missing_or_invalid_ids(self):
        """
        Distinguish invalid supplied identifiers from absent or blank identifiers
        """
        numeric = self._data("Numeric identifier", 123)
        padded = self._data("Padded identifier", " padded-id ")
        missing = self._data("Missing identifier")
        blank = self._data("Blank identifier", "   ")
        fallback = self._data("")
        identified = self._data("", "available-id")
        for data in (missing, blank, fallback):
            data.pop("phase")
        response = self._upload(("identifiers.json", [numeric, padded, missing, blank, fallback, identified]))
        self.assertEqual(JSONData.objects.count(), 0)
        objects = _marked(self._report(response), "data-upload-object")
        self.assertEqual(len(objects), 6)
        for node, expected in zip(objects, ["invalid_identifier", "invalid_identifier",
                                           "missing_required", "missing_required", "missing_required",
                                           "empty_values"]):
            categories = _marked(node, "data-upload-category")
            self.assertEqual(dict(categories[0].attributes)["data-upload-category"], expected)
        self.assertIn("text", _text(objects[0]).casefold())
        self.assertIn("whitespace", _text(objects[1]).casefold())
        self.assertNotIn("123", _text(objects[0], header_only=True))
        self.assertNotIn("padded-id", _text(objects[1], header_only=True))
        for node, title in zip(objects[2:4], ["Missing identifier", "Blank identifier"]):
            header = _text(node, header_only=True)
            self.assertIn(title, header)
            self.assertNotRegex(header, r"\b[0-9a-z]{8}\b")
        self.assertRegex(_text(objects[4], header_only=True).casefold(), r"object\s+5\b")
        self.assertIn("available-id", _text(objects[5], header_only=True))

    def test_duplicate_identifiers_keep_original_data_and_report_the_failed_objects(self):
        """
        Reject the whole file while identifying duplicates and preserving stored data
        """
        existing = JSONData.objects.create(
            owner=self.other, access_type="c", data=self._data("Private original", "stored-id"),
        )
        response = self._upload(("duplicates.json", [
            self._data("Rejected stored duplicate", "stored-id"),
            self._data("Unstored batch original", "batch-id"),
            self._data("Rejected batch duplicate", "batch-id"),
        ]))
        self.assertEqual(JSONData.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.data["title"], "Private original")
        self.assertEqual(existing.owner, self.other)
        self.assertEqual(existing.access_type, "c")
        self.assertFalse(JSONData.objects.filter(owner=self.owner).exists())
        self.assertFalse(JSONData.objects.filter(data__identifier="batch-id").exists())
        report = self._report(response)
        self.assertNotIn("Private original", _text(report))
        objects = _marked(report, "data-upload-object")
        self.assertEqual(len(objects), 2)
        for node, title, identifier in [
            (objects[0], "Rejected stored duplicate", "stored-id"),
            (objects[1], "Rejected batch duplicate", "batch-id"),
        ]:
            self.assertIn(title, _text(node, header_only=True))
            self.assertIn(identifier, _text(node, header_only=True))
            categories = _marked(node, "data-upload-category")
            self.assertEqual(len(categories), 1)
            self.assertEqual(dict(categories[0].attributes)["data-upload-category"], "duplicate_identifier")

    def test_report_escapes_uploaded_text_and_survives_the_redirect_as_html(self):
        """
        Escape uploaded labels and usernames while rendering the report structure
        """
        filename = "input<img src=x onerror=alert(1)>.json"
        title = "<img src=x onerror=alert(2)>"
        identifier = "<svg onload=alert(3)>"
        username = "<img src=x onerror=alert(4)>"
        data = self._data(title, identifier)
        data["shared_with"] = [{"access_type": "c", "username": username}]
        response = self._upload((filename, data))
        report = self._report(response)
        html = response.content.decode()
        for value in (filename, title, identifier, username):
            self.assertIn(str(escape(value)), html)
            self.assertNotIn(value, html)
            self.assertIn(value, _text(report))
        self.assertFalse(any(node.name in {"img", "svg", "script"} for node in _elements(report)))
        self.assertEqual(JSONData.objects.count(), 0)

    def test_success_has_no_error_report_and_refresh_does_not_upload_again(self):
        """
        Generate missing identifiers normally and keep refreshing the result harmless
        """
        null_identifier = dict(self._data("Null id accepted"), identifier=None)
        response = self._upload(("valid.json", [
            self._data("Missing id accepted"), self._data("Blank id accepted", " "), null_identifier,
        ]))
        self.assertEqual(JSONData.objects.count(), 3)
        self.assertFalse(_marked(parse_html(response.content.decode()), "data-upload-report"))
        for stored in JSONData.objects.all():
            self.assertRegex(stored.data["identifier"], r"^[0-9a-z]{8}$")
        refreshed = self.client.get(reverse("upload_json"))
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(JSONData.objects.count(), 3)
        self.assertFalse(_marked(parse_html(refreshed.content.decode()), "data-upload-report"))
