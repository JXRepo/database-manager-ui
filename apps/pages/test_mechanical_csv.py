import csv
import io
import json
import zipfile
from copy import deepcopy

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class MechanicalCSVTests(TestCase):
    """
    Verify mechanical CSV content, selection, and download permissions
    """

    def setUp(self):
        """
        Create private, public, and shared synthetic curve records
        """
        self.owner = User.objects.create_user(username="csv-owner")
        self.viewer = User.objects.create_user(username="csv-viewer")
        self.data = {
            "identifier": "curve-example",
            "title": "Synthetic curves",
            "units": {"Stress": "MPa", "Strain": 1},
            "stress": {"stress_11": [1.234567890123, -2, 3]},
            "total_strain": {"strain_11": [0, 0.01]},
            "plastic_strain": {"equivalent_plastic_strain": [0, 0.002, 0.004, 0.006]},
        }
        self.private = self.make_object("c")
        self.public = self.make_object("all")
        self.shared = self.make_object("c")
        self.shared.shared_users.add(self.viewer)
        self.client.force_login(self.owner)

    def make_object(self, access, data=None):
        """
        Store a small synthetic data object

        Parameters
        ----------
        access : str
            Access mode for the record.
        data : dict, optional
            Alternative curve payload.

        Returns
        -------
        JSONData
            Persisted test record.
        """
        payload = deepcopy(self.data if data is None else data)
        return JSONData.objects.create(
            owner=self.owner, data=payload, access_type=access,
            size_bytes=len(json.dumps(payload)),
        )

    def download(self, response):
        """
        Read and close a streaming attachment

        Parameters
        ----------
        response : HttpResponse
            Response returned by the test client.

        Returns
        -------
        bytes
            Downloaded file content.
        """
        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content)
        response.close()
        return content

    def test_all_csv_keeps_precision_units_and_unequal_lengths(self):
        """
        Preserve every sample and leave missing tail cells empty
        """
        response = self.client.get(reverse("mechanical_csv_export", args=[self.private.pk]))
        self.assertIn("text/csv", response["Content-Type"])
        rows = list(csv.reader(io.StringIO(self.download(response).decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["index", "stress.stress_11 [MPa]", "total_strain.strain_11", "plastic_strain.equivalent_plastic_strain"])
        self.assertEqual(rows[1], ["0", "1.234567890123", "0", "0"])
        self.assertEqual(rows[-1], ["3", "", "", "0.006"])
        self.private.refresh_from_db()
        self.assertEqual(self.private.data, self.data)

    def test_selected_fields_keep_requested_order_and_deduplicate(self):
        """
        Export exactly the requested series without truncating longer columns
        """
        fields = ["total_strain.strain_11", "stress.stress_11", "stress.stress_11"]
        response = self.client.get(reverse("mechanical_csv_export", args=[self.private.pk]), {"scope": "selected", "fields": fields})
        rows = list(csv.reader(io.StringIO(self.download(response).decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["index", "total_strain.strain_11", "stress.stress_11 [MPa]"])
        self.assertEqual(rows[-1], ["2", "", "3"])

    def test_invalid_or_empty_selection_does_not_export_everything(self):
        """
        Reject stale and empty column selections with actionable feedback
        """
        for params in ({"scope": "selected"}, {"scope": "selected", "fields": ["stress.missing"]}, {"scope": "wrong"}):
            with self.subTest(params=params):
                response = self.client.get(reverse("mechanical_csv_export", args=[self.private.pk]), params)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(list(get_messages(response.wsgi_request)))

    def test_single_download_enforces_access(self):
        """
        Allow public and explicitly shared records but hide private records
        """
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("mechanical_csv_export", args=[self.private.pk])).status_code, 404)
        for obj in (self.public, self.shared):
            self.assertTrue(self.download(self.client.get(reverse("mechanical_csv_export", args=[obj.pk]))))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("mechanical_csv_export", args=[self.public.pk])).status_code, 302)

    def test_five_objects_make_five_unique_csv_entries(self):
        """
        Package selected records with colliding identifiers without overwriting
        """
        objects = [self.private, self.public, self.shared, self.make_object("c"), self.make_object("c")]
        response = self.client.post(reverse("export_selected_my_data_csv"), {"selected_objects": [o.pk for o in objects] + [self.private.pk]})
        self.assertEqual(response["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(self.download(response))) as archive:
            self.assertEqual(len(archive.namelist()), 5)
            self.assertEqual(len(set(archive.namelist())), 5)
            for name in archive.namelist():
                self.assertTrue(name.endswith(".csv"))
                self.assertNotIn("/", name)
                self.assertEqual(len(list(csv.reader(io.StringIO(archive.read(name).decode("utf-8-sig"))))), 5)

    def test_one_bulk_selection_returns_csv(self):
        """
        Avoid a ZIP wrapper for a single selected record
        """
        response = self.client.post(reverse("export_selected_my_data_csv"), {"selected_objects": [self.private.pk]})
        self.assertIn("text/csv", response["Content-Type"])
        self.download(response)

    def test_search_bulk_access_and_atomic_rejection(self):
        """
        Export accessible selections and reject a batch containing private data
        """
        self.client.force_login(self.viewer)
        response = self.client.post(reverse("export_selected_search_csv"), {"selected_objects": [self.public.pk, self.shared.pk]})
        with zipfile.ZipFile(io.BytesIO(self.download(response))) as archive:
            self.assertEqual(len(archive.namelist()), 2)
        for ids in ([self.public.pk, self.private.pk], [self.public.pk, 999999], [], ["bad"], [str(2**100)]):
            response = self.client.post(reverse("export_selected_search_csv"), {"selected_objects": ids})
            self.assertEqual(response.status_code, 302)
            self.assertNotIn("Content-Disposition", response)
        response = self.client.post(reverse("export_selected_my_data_csv"), {"selected_objects": [self.public.pk]})
        self.assertEqual(response.status_code, 302)

    def test_no_curves_does_not_create_misleading_empty_files(self):
        """
        Report records without numeric curves instead of silently skipping them
        """
        empty = self.make_object("c", {"title": "No curves", "stress": {}})
        response = self.client.get(reverse("mechanical_csv_export", args=[empty.pk]))
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("export_selected_my_data_csv"), {"selected_objects": [self.private.pk, empty.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(list(get_messages(response.wsgi_request)))

    def test_calculated_equivalent_columns_are_identified(self):
        """
        Distinguish derived equivalents from supplied curves in CSV headers
        """
        data = deepcopy(self.data)
        data["stress"] = {"stress_" + c: [12, 24] if c == "11" else [0, 0] for c in ("11", "22", "33", "12", "13", "23")}
        obj = self.make_object("c", data)
        rows = list(csv.reader(io.StringIO(self.download(self.client.get(reverse("mechanical_csv_export", args=[obj.pk]))).decode("utf-8-sig"))))
        self.assertIn("stress.equivalent_stress [MPa] (calculated)", rows[0])
        self.assertEqual(rows[1][rows[0].index("stress.equivalent_stress [MPa] (calculated)")], "12.0")

    def test_headers_quote_commas_unicode_and_formula_prefixes(self):
        """
        Preserve unit text and neutralize spreadsheet formulas in field paths
        """
        data = {"=unsafe": {"stress_11": [-2, 3]}, "units": {"Stress": "MPa, 测试"}}
        obj = self.make_object("c", data)
        rows = list(csv.reader(io.StringIO(self.download(self.client.get(reverse("mechanical_csv_export", args=[obj.pk]))).decode("utf-8-sig"))))
        self.assertEqual(rows[0][1], "'=unsafe.stress_11 [MPa, 测试]")
        self.assertEqual(rows[1][1], "-2")

    def test_bulk_is_post_only_and_requires_login(self):
        """
        Protect bulk selection endpoints with authentication and POST semantics
        """
        for name in ("export_selected_my_data_csv", "export_selected_search_csv"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 405)
        self.client.logout()
        for name in ("export_selected_my_data_csv", "export_selected_search_csv"):
            self.assertEqual(self.client.post(reverse(name), {"selected_objects": [self.public.pk]}).status_code, 302)
