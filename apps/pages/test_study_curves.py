"""
Verify bounded access to complete recorded curves for study comparisons
"""

from copy import deepcopy
import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.http import Http404, QueryDict
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import JSONData, ResearchCollection
from .study_curves import collection_study_curves, curve_parameters, selection_study_curves


class StudyCurveTests(TestCase):
    """
    Keep source arrays, access checks and units explicit in comparative results
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create owned, public, shared and inaccessible records with cyclic arrays
        """
        cls.viewer = User.objects.create_user(username="study-curve-viewer")
        cls.other = User.objects.create_user(username="study-curve-other")
        cls.data = {
            "identifier": "curve-reference", "title": "Reference curve",
            "units": {"Stress": "MPa", "Strain": "1"},
            "stress": {"stress_11": [0, 2.123456789, -3, 1], "equivalent_stress": [0, 2, 3, 1]},
            "total_strain": {"strain_11": [0, 0.02, -0.01, 0.01], "equivalent_strain": [0, 0.02, 0.03, 0.01]},
            "plastic_strain": {"plastic_strain_11": [0, 0.001, 0.002, 0.003]},
        }
        cls.reference = JSONData.objects.create(owner=cls.viewer, data=cls.data)
        second = deepcopy(cls.data)
        second.update(identifier="curve-public", title="Public curve")
        cls.public = JSONData.objects.create(owner=cls.other, access_type="all", data=second)
        second = deepcopy(cls.data)
        second.update(identifier="curve-shared", title="Shared curve")
        cls.shared = JSONData.objects.create(owner=cls.other, access_type="c", data=second)
        cls.shared.shared_users.add(cls.viewer)
        cls.hidden = JSONData.objects.create(owner=cls.other, data={**cls.data, "title": "SECRET curve"})
        cls.collection = ResearchCollection.objects.create(owner=cls.viewer, title="Curve study")
        cls.collection.members.add(cls.reference, cls.public, cls.shared, cls.hidden)

    def setUp(self):
        """
        Use an authenticated request factory without depending on route integration
        """
        self.factory = RequestFactory()
        self.client.force_login(self.viewer)

    def response(self, query=None, *, user=None):
        """
        Call the real collection endpoint with a selectable comparison query

        Parameters
        ----------
        query : dict or str or None, optional
            Submitted GET controls, defaulting to two accessible cyclic records.
        user : User or AnonymousUser or None, optional
            Viewer to exercise authentication and ownership.

        Returns
        -------
        HttpResponse
            The endpoint response after its decorators and access checks.
        """
        if query is None:
            query = {"compare": f"{self.reference.pk},{self.public.pk}", "curve_component": "11"}
        request = self.factory.get("/study-curves/", data=query)
        request.user = self.viewer if user is None else user
        request.session = self.client.session
        return collection_study_curves(request, self.collection.pk)

    def test_full_cyclic_arrays_and_selection_order_are_preserved(self):
        """
        Return exact paired samples without sorting, interpolation or raw data writes
        """
        response = self.response({"compare": f"{self.public.pk},{self.reference.pk}", "curve_component": "11"})
        self.assertEqual(response.status_code, 200)
        payload = response.json() if hasattr(response, "json") else json.loads(response.content)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selection"], [self.public.pk, self.reference.pk])
        record = payload["records"][1]
        self.assertEqual(record["x"], self.data["total_strain"]["strain_11"])
        self.assertEqual(record["y"], self.data["stress"]["stress_11"])
        self.assertEqual(record["paired_count"], 4)
        self.assertEqual(record["state"], "ready")
        self.assertTrue(payload["overlay_allowed"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.reference.refresh_from_db()
        self.assertEqual(self.reference.data, self.data)

    def test_missing_or_revoked_member_rejects_the_whole_selection(self):
        """
        Never return a partial curve set after access or membership changes
        """
        for unavailable in (self.hidden.pk, 9223372036854775807):
            response = self.response({"compare": f"{self.reference.pk},{unavailable}"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(json.loads(response.content)["records"], [])
            self.assertNotIn("SECRET", response.content.decode())
        self.shared.shared_users.clear()
        response = self.response({"compare": f"{self.reference.pk},{self.shared.pk}"})
        self.assertEqual(response.status_code, 400)
        self.collection.members.remove(self.public)
        self.assertEqual(self.response().status_code, 400)

    def test_owner_and_authentication_checks_apply_before_curve_access(self):
        """
        Protect the workspace even when its data objects are public
        """
        self.assertEqual(self.response(user=AnonymousUser()).status_code, 302)
        with self.assertRaises(Http404):
            self.response(user=self.other)

    def test_invalid_repeated_or_oversized_controls_fail_closed(self):
        """
        Validate every curve selector and the entire two to four record selection
        """
        valid = f"compare={self.reference.pk},{self.public.pk}"
        for query in ("", f"compare={self.reference.pk}", valid + "&compare=1,2", "compare=1,1",
                      "compare=1,2,3,4,5", valid + "&curve_component=11&curve_component=22",
                      valid + "&curve_component=12x", valid + "&curve_strain=elastic",
                      valid + "&curve_strain=total&curve_strain=plastic"):
            with self.subTest(query=query):
                response = self.response(QueryDict(query))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(json.loads(response.content)["records"], [])
        self.assertEqual(curve_parameters(QueryDict("")), {"curve_component": "equivalent", "curve_strain": "total"})

    def test_missing_and_unknown_units_allow_inspection_but_not_overlay(self):
        """
        Require explicit recognized equal units instead of trusting matching text
        """
        for units in ({"Stress": "mystery", "Strain": "1"}, {"Stress": "MPa"},
                      {"Stress": "Pa", "Strain": "1"}, {"Stress": "MPa", "Strain": "%"}):
            with self.subTest(units=units):
                data = deepcopy(self.data)
                data["units"] = units
                self.public.data = data
                self.public.save(update_fields=["data"])
                payload = json.loads(self.response().content)
                self.assertFalse(payload["overlay_allowed"])
                self.assertTrue(payload["overlay_reason"])
                self.assertTrue(all(row["state"] == "ready" for row in payload["records"]))
        for obj in (self.reference, self.public):
            obj.data = deepcopy(self.data)
            obj.data["units"]["Stress"] = "mystery"
            obj.save(update_fields=["data"])
        self.assertFalse(json.loads(self.response().content)["overlay_allowed"])

    def test_tail_counts_and_plastic_strain_are_explicit(self):
        """
        Keep each recorded path and paired count without inventing unmatched values
        """
        data = deepcopy(self.data)
        data["plastic_strain"]["plastic_strain_11"] = [0, 0.001]
        self.reference.data = data
        self.reference.save(update_fields=["data"])
        payload = json.loads(self.response({"compare": f"{self.reference.pk},{self.public.pk}",
                                            "curve_component": "11", "curve_strain": "plastic"}).content)
        record = payload["records"][0]
        self.assertEqual(record["x"], [0, 0.001])
        self.assertEqual(record["y"], [0, 2.123456789])
        self.assertEqual((record["x_count"], record["y_count"], record["paired_count"]), (2, 4, 2))
        self.assertEqual(record["x_path"], "plastic_strain.plastic_strain_11")

    def test_equivalent_curves_use_existing_formula_only_when_absent(self):
        """
        Mark eligible calculated series and keep supplied empty equivalents authoritative
        """
        data = deepcopy(self.data)
        for name, prefix in (("stress", "stress"), ("total_strain", "strain")):
            data[name] = {f"{prefix}_{component}": [0, 0] for component in ("11", "22", "33", "12", "13", "23")}
            data[name][f"{prefix}_11"] = [0, 3]
        self.reference.data = data
        self.reference.save(update_fields=["data"])
        query = {"compare": f"{self.reference.pk},{self.public.pk}"}
        record = json.loads(self.response(query).content)["records"][0]
        self.assertTrue(record["calculated_x"])
        self.assertTrue(record["calculated_y"])
        self.assertEqual(record["y"], [0, 3])
        self.assertEqual(record["x"], [0, 2])
        data["stress"]["equivalent_stress"] = []
        self.reference.save(update_fields=["data"])
        payload = json.loads(self.response(query).content)
        self.assertEqual(payload["records"][0]["state"], "missing")
        self.assertEqual(payload["records"][0]["x"], [])
        self.assertFalse(payload["overlay_allowed"])

    def test_ambiguous_sources_and_units_do_not_select_an_alias(self):
        """
        Treat conflicting mechanical values or parents as unavailable for this record
        """
        variants = []
        data = deepcopy(self.data)
        data["stress"]["Stress 11"] = [0, 8, 9]
        variants.append(data)
        data = deepcopy(self.data)
        data["Stress"] = {"stress_11": [0, 8, 9]}
        variants.append(data)
        data = deepcopy(self.data)
        data["units"]["stress"] = "Pa"
        variants.append(data)
        data = deepcopy(self.data)
        data["stress"]["stress_11"] = [0, "0.10000000000000000001"]
        data["stress"]["Stress 11"] = [[0], ["0.10000000000000000002"]]
        variants.append(data)
        for data in variants:
            with self.subTest(data=data):
                self.reference.data = data
                self.reference.save(update_fields=["data"])
                payload = json.loads(self.response().content)
                self.assertEqual(payload["records"][0]["state"], "ambiguous")
                self.assertEqual(payload["records"][0]["x"], [])
                self.assertFalse(payload["overlay_allowed"])

    def test_known_aliases_and_scalar_wrappers_match_detail_semantics(self):
        """
        Read recognized top-level groups while ignoring unrelated nested curves
        """
        self.reference.data = {
            "Title": ["Wrapped curve"], "Units": [{"Stress": ["MPa"], "Strain": [1]}],
            "Stress": [{"Stress 11": [0, "2.123456789", -3]}],
            "Total Strain": [{"Strain 11": [0, "0.02", -0.01]}],
            "extra": {"stress_11": [100, 200], "strain_11": [0, 5]},
        }
        self.reference.save(update_fields=["data"])
        record = json.loads(self.response().content)["records"][0]
        self.assertEqual(record["y"], [0, 2.123456789, -3])
        self.assertEqual(record["x"], [0, 0.02, -0.01])
        self.assertEqual(record["state"], "ready")

    def test_equal_known_wrappers_in_duplicate_sources_remain_plotable(self):
        """
        Accept equivalent scalar and object wrappers without unwrapping genuine curves
        """
        self.reference.data = deepcopy(self.data)
        self.reference.data["units"]["STRAIN"] = ["1"]
        self.reference.data["Units"] = [{"Stress": ["MPa"], "Strain": ["1"], "STRAIN": "1"}]
        self.reference.data["Stress"] = [{
            "Stress 11": [[number] for number in self.data["stress"]["stress_11"]],
            "Equivalent Stress": self.data["stress"]["equivalent_stress"],
        }]
        self.reference.save(update_fields=["data"])
        record = json.loads(self.response().content)["records"][0]
        self.assertEqual(record["state"], "ready")
        self.assertEqual(record["y"], self.data["stress"]["stress_11"])

    def test_actual_bytes_and_sample_limits_reject_the_whole_request(self):
        """
        Do not trust declared sizes or return partially truncated curve sets
        """
        JSONData.objects.filter(pk__in=[self.reference.pk, self.public.pk]).update(size_bytes=1)
        with patch("apps.pages.study_curves.MAX_CURVE_BYTES", 40), \
                patch("apps.pages.study_curves._record_curve", side_effect=AssertionError("raw data loaded")):
            response = self.response()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(json.loads(response.content)["records"], [])
        with patch("apps.pages.study_curves.MAX_CURVE_POINTS", 7):
            response = self.response()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(json.loads(response.content)["records"], [])

    def test_temporary_selection_requires_all_original_members_to_remain_accessible(self):
        """
        Reject a stale unpinned member rather than silently shrinking a saved selection
        """
        created = self.client.post(reverse("graph_selection_create"), {
            "selected_objects": [self.reference.pk, self.public.pk, self.shared.pk],
        })
        token = created.url.rstrip("/").rsplit("/", 1)[-1]
        request = self.factory.get("/study-curves/", {"compare": f"{self.reference.pk},{self.public.pk}"})
        request.user = self.viewer
        request.session = self.client.session
        self.assertEqual(selection_study_curves(request, token).status_code, 200)
        self.shared.shared_users.clear()
        response = selection_study_curves(request, token)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["records"], [])

    def test_unpaired_tails_do_not_consume_the_paired_sample_allowance(self):
        """
        Retain complete paired curves and original tail counts within the explicit budget
        """
        self.reference.data = deepcopy(self.data)
        self.reference.data["total_strain"]["strain_11"] = list(range(12))
        self.reference.save(update_fields=["data"])
        self.public.data = deepcopy(self.data)
        self.public.data["total_strain"]["strain_11"] = [0]
        self.public.data["stress"]["stress_11"] = [0]
        self.public.save(update_fields=["data"])
        with patch("apps.pages.study_curves.MAX_CURVE_POINTS", 7):
            response = self.response()
        self.assertEqual(response.status_code, 200)
        first = json.loads(response.content)["records"][0]
        self.assertEqual(first["paired_count"], 4)
        self.assertEqual(first["x_count"], 12)
        self.assertEqual(first["x"], [0, 1, 2, 3])
        self.assertEqual(first["y"], self.data["stress"]["stress_11"])

    def test_calculated_equivalent_uses_only_paired_samples_but_keeps_full_count(self):
        """
        Bound equivalent calculation work without pretending an unpaired tail is absent
        """
        from .views import _calculate_equivalent_strain

        self.reference.data = deepcopy(self.data)
        self.reference.data["total_strain"] = {
            f"strain_{component}": list(range(12)) if component == "11" else [0] * 12
            for component in ("11", "22", "33", "12", "13", "23")
        }
        self.reference.save(update_fields=["data"])
        self.public.data = deepcopy(self.data)
        self.public.data["total_strain"]["equivalent_strain"] = [0]
        self.public.data["stress"]["equivalent_stress"] = [0]
        self.public.save(update_fields=["data"])
        with patch("apps.pages.study_curves.MAX_CURVE_POINTS", 7), \
                patch("apps.pages.views._calculate_equivalent_strain", wraps=_calculate_equivalent_strain) as calculate:
            response = self.response({"compare": f"{self.reference.pk},{self.public.pk}"})
        self.assertEqual(response.status_code, 200)
        first = json.loads(response.content)["records"][0]
        self.assertTrue(first["calculated_x"])
        self.assertEqual(first["x_count"], 12)
        self.assertEqual(first["paired_count"], 4)
        self.assertEqual(len(first["x"]), 4)
        self.assertEqual(calculate.call_count, 1)
        self.assertTrue(all(len(values) == 4 for values in calculate.call_args.args[0].values()))
