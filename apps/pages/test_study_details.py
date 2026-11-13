"""
Verify exact bounded parameter inspection and complete study access checks
"""

from copy import deepcopy
import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from .models import JSONData, ResearchCollection
from .study_details import build_parameter_context
from .temporary_selections import create_selection


class StudyParameterTests(TestCase):
    """
    Keep recorded model and load differences visible without changing source JSON
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create private, public, shared and unavailable study members
        """
        cls.owner = User.objects.create_user(username="parameter-owner")
        cls.other = User.objects.create_user(username="parameter-other")
        cls.data = {
            "title": "Reference parameters", "identifier": "parameter-reference",
            "phase": [{"phase_name": "Copper", "constitutive_model": {
                "elastic_model_name": "Cubic", "elastic_parameters": {"C11": "168.4000000000000000001", "enabled": False},
                "plastic_model_name": "Crystal", "plastic_parameters": {"hardening": {"initial": 0, "rate": 1.0}},
                "damage_model_name": "Recorded damage", "damage_parameters": {"threshold": 0},
                "units": {"C11": "GPa", "hardening": {"initial": "MPa"}},
            }}],
            "mechanical_BC": [{"loading_type": "stress", "loading_mode": "static", "vertex_list": ["V1", "V2"],
                               "constraints": ["loaded"], "applied_load": [
                                   {"step": 0.5, "magnitude": {"xx": "0.10000000000000000001", "xy": 0, "yx": -2}, "duration": 1},
                                   {"step": 2, "magnitude": {"xx": 5, "xy": 1, "yx": -1}},
                               ]}],
            "units": {"Stress": "MPa", "Strain": 1, "Time": "s"},
        }
        cls.first = JSONData.objects.create(owner=cls.owner, data=cls.data)
        cls.public = JSONData.objects.create(owner=cls.other, access_type="all", data={**deepcopy(cls.data), "title": "Public parameters"})
        cls.shared = JSONData.objects.create(owner=cls.other, access_type="c", data=deepcopy(cls.data))
        cls.shared.shared_users.add(cls.owner)
        cls.hidden = JSONData.objects.create(owner=cls.other, data={"title": "SECRET inaccessible parameters"})
        cls.collection = ResearchCollection.objects.create(owner=cls.owner, title="Parameter study")
        cls.collection.members.add(cls.first, cls.public, cls.shared, cls.hidden)

    def setUp(self):
        """
        Prepare an authenticated native workspace request with a real browser session
        """
        self.client.force_login(self.owner)
        self.request = RequestFactory().get("/study/?inspect=1")
        self.request.user = self.owner
        self.request.session = self.client.session

    def inspect(self, ids=None, **kwargs):
        """
        Call the inspection service with the current collection by default

        Parameters
        ----------
        ids : list of int or None, optional
            Selected records, defaulting to the reference and public record.
        **kwargs : object
            Explicit saved or temporary scope.

        Returns
        -------
        dict
            Inspection result after independent ownership and access checks.
        """
        if ids is None:
            ids = [self.first.pk, self.public.pk]
        if not kwargs:
            kwargs = {"collection": self.collection}
        return build_parameter_context(self.request, ids, **kwargs)

    def save_public(self, data):
        """
        Replace one fixture's raw JSON through the ordinary model save path

        Parameters
        ----------
        data : dict
            New original source metadata.
        """
        self.public.data = data
        self.public.save(update_fields=["data"])

    def rows(self, context):
        """
        Index native table rows by their precise positional path

        Parameters
        ----------
        context : dict
            Inspection response.

        Returns
        -------
        dict
            Row lookup used by focused assertions.
        """
        return {row["path"]: row for row in context["rows"]}

    def test_model_names_do_not_hide_different_precise_parameters(self):
        """
        Compare the actual elastic, plastic and damage values behind equal names
        """
        data = deepcopy(self.data)
        model = data["phase"][0]["constitutive_model"]
        model["elastic_parameters"]["C11"] = "168.4000000000000000002"
        model["plastic_parameters"]["hardening"]["rate"] = 2.0
        model["damage_parameters"]["threshold"] = 3
        self.save_public(data)
        context = self.inspect([self.public.pk, self.first.pk])
        rows = self.rows(context)
        self.assertTrue(context["ready"])
        self.assertFalse(context["limited"])
        self.assertEqual([obj["pk"] for obj in context["objects"]], [self.public.pk, self.first.pk])
        base = "phase[0].constitutive_model."
        self.assertEqual(rows[base + "elastic_model_name"]["status"], "same")
        for field in ("elastic_parameters.C11", "plastic_parameters.hardening.rate", "damage_parameters.threshold"):
            self.assertEqual(rows[base + field]["status"], "different")
        self.assertIn("168.4000000000000000002", rows[base + "elastic_parameters.C11"]["cells"][0]["value"])
        self.assertEqual(rows[base + "elastic_parameters.C11"]["cells"][0]["value_type"], "string")
        self.first.refresh_from_db()
        self.assertEqual(self.first.data, self.data)

    def test_nested_loads_keep_steps_tensor_asymmetry_and_array_order(self):
        """
        Retain every supplied condition position, step and distinct tensor component
        """
        data = deepcopy(self.data)
        data["mechanical_BC"][0]["applied_load"][0]["magnitude"]["yx"] = 2
        data["mechanical_BC"].append({"loading_type": "force", "applied_load": [{"step": 0, "magnitude": -10}]})
        self.save_public(data)
        rows = self.rows(self.inspect())
        base = "mechanical_BC[0].applied_load[0]."
        self.assertEqual(rows[base + "step"]["cells"][0]["value"], "0.5")
        self.assertEqual(rows[base + "magnitude.xy"]["status"], "same")
        self.assertEqual(rows[base + "magnitude.yx"]["status"], "different")
        self.assertEqual(rows["mechanical_BC[1].applied_load[0].magnitude"]["status"], "incomplete")
        self.assertEqual(rows["mechanical_BC[1].applied_load[0].magnitude"]["cells"][1]["value"], "-10")

    def test_zero_false_and_original_types_are_not_empty_or_interchangeable(self):
        """
        Preserve false and zero while distinguishing integers, floats and numeric text
        """
        data = deepcopy(self.data)
        parameters = data["phase"][0]["constitutive_model"]["plastic_parameters"]["hardening"]
        parameters["initial"] = "0"
        parameters["rate"] = 1
        self.save_public(data)
        rows = self.rows(self.inspect())
        base = "phase[0].constitutive_model."
        self.assertEqual(rows[base + "elastic_parameters.enabled"]["cells"][0]["value"], "false")
        self.assertEqual(rows[base + "elastic_parameters.enabled"]["status"], "same")
        self.assertEqual(rows[base + "plastic_parameters.hardening.initial"]["status"], "different")
        self.assertEqual(rows[base + "plastic_parameters.hardening.rate"]["status"], "different")

    def test_arbitrary_parameter_names_keep_case_punctuation_and_parent(self):
        """
        Avoid inferring aliases for freeform names or moving values across parents
        """
        data = deepcopy(self.data)
        parameters = data["phase"][0]["constitutive_model"]["elastic_parameters"]
        parameters["c11"] = parameters.pop("C11")
        parameters["rate.a"] = 2
        parameters["rate"] = {"a": 2}
        self.save_public(data)
        rows = self.rows(self.inspect())
        base = "phase[0].constitutive_model.elastic_parameters."
        self.assertEqual(rows[base + "C11"]["status"], "incomplete")
        self.assertEqual(rows[base + "c11"]["status"], "incomplete")
        self.assertIn('phase[0].constitutive_model.elastic_parameters["rate.a"]', rows)
        self.assertIn(base + "rate.a", rows)

    def test_model_units_remain_separate_from_global_and_parameter_names(self):
        """
        Show missing or differing unit declarations without guessing their mappings
        """
        data = deepcopy(self.data)
        data["units"]["Stress"] = "GPa"
        data["phase"][0]["constitutive_model"]["units"]["C11"] = "MPa"
        self.save_public(data)
        rows = self.rows(self.inspect())
        self.assertEqual(rows["units.Stress"]["status"], "different")
        unit_path = "phase[0].constitutive_model.units.C11"
        self.assertEqual(rows[unit_path]["status"], "different")
        self.assertIn("model units", rows[unit_path]["group"])
        del data["phase"][0]["constitutive_model"]["units"]
        self.save_public(data)
        rows = self.rows(self.inspect())
        self.assertEqual(rows[unit_path]["status"], "incomplete")
        self.assertEqual(rows["phase[0].constitutive_model.units"]["status"], "incomplete")

    def test_known_aliases_and_wrappers_keep_original_source_paths(self):
        """
        Unwrap known schema values while leaving arbitrary parameter arrays intact
        """
        data = deepcopy(self.data)
        model = data["phase"][0].pop("constitutive_model")
        model["Elastic Model Name"] = [model.pop("elastic_model_name")]
        model["Elastic Parameters"] = [model.pop("elastic_parameters")]
        data["phase"][0]["Constitutive Model"] = [model]
        data["Phase"] = [[data.pop("phase")[0]]]
        data["Units"] = [{key: value if key == "Time" else [value] for key, value in data.pop("units").items()}]
        data["Mechanical BC"] = data.pop("mechanical_BC")
        data["Mechanical BC"][0]["applied_load"][0]["step"] = [0.5]
        self.save_public(data)
        context = self.inspect()
        self.assertEqual(context["counts"]["different"], 0)
        self.assertEqual(context["counts"]["incomplete"], 0)
        row = self.rows(context)["phase[0].constitutive_model.elastic_model_name"]
        self.assertIn('["Constitutive Model"][0]["Elastic Model Name"][0]', row["cells"][1]["source_paths"][0])
        data["Phase"][0][0]["Constitutive Model"][0]["Elastic Parameters"][0]["C11"] = ["168.4000000000000000001"]
        self.save_public(data)
        self.assertGreater(self.inspect()["counts"]["incomplete"], 0)

    def test_duplicate_precise_aliases_never_round_into_equality(self):
        """
        Detect deep numeric string conflicts before any floating point conversion
        """
        data = deepcopy(self.data)
        magnitude = data["mechanical_BC"][0]["applied_load"][0]["magnitude"]
        magnitude["XX"] = ["0.10000000000000000002"]
        self.save_public(data)
        row = self.rows(self.inspect())["mechanical_BC[0].applied_load[0].magnitude.xx"]
        self.assertEqual(row["status"], "incomplete")
        self.assertEqual(row["cells"][1]["state"], "ambiguous")
        self.assertEqual(len(row["cells"][1]["source_paths"]), 2)
        magnitude["XX"] = [magnitude["xx"]]
        self.save_public(data)
        self.assertEqual(self.rows(self.inspect())[row["path"]]["status"], "same")

    def test_conflicting_parent_aliases_do_not_choose_a_model_or_unit_value(self):
        """
        Propagate source ambiguity instead of using a convenient first parent
        """
        data = deepcopy(self.data)
        model = data["phase"][0]["constitutive_model"]
        model["Elastic Parameters"] = {"C11": "different"}
        data["Units"] = {"Stress": "Pa"}
        self.save_public(data)
        rows = self.rows(self.inspect())
        self.assertEqual(rows["phase[0].constitutive_model.elastic_parameters"]["cells"][1]["state"], "ambiguous")
        self.assertEqual(rows["units"]["cells"][1]["state"], "ambiguous")
        self.assertEqual(rows["units.Stress"]["status"], "incomplete")

    def test_phase_reordering_keeps_recorded_positions(self):
        """
        Avoid aligning equal phase labels across different array positions
        """
        data = deepcopy(self.data)
        second = deepcopy(data["phase"][0])
        second["phase_name"] = "Nickel"
        second["constitutive_model"]["elastic_parameters"]["C11"] = "250"
        data["phase"].append(second)
        self.first.data = data
        self.first.save(update_fields=["data"])
        data = deepcopy(data)
        data["phase"].reverse()
        self.save_public(data)
        rows = self.rows(self.inspect())
        for position in (0, 1):
            self.assertEqual(rows[f"phase[{position}].phase_name"]["status"], "different")
            self.assertEqual(rows[f"phase[{position}].constitutive_model.elastic_parameters.C11"]["status"], "different")

    def test_empty_missing_and_blank_wrappers_are_incomplete(self):
        """
        Never classify matching absence or empty values as complete evidence
        """
        for empty in (None, "", "  ", [], {}, [None]):
            with self.subTest(empty=empty):
                data = deepcopy(self.data)
                data["phase"][0]["constitutive_model"]["elastic_model_name"] = empty
                self.save_public(data)
                row = self.rows(self.inspect())["phase[0].constitutive_model.elastic_model_name"]
                self.assertEqual(row["status"], "incomplete")
                self.assertEqual(row["cells"][1]["state"], "not_supplied")

    def test_array_display_row_and_depth_limits_are_explicit(self):
        """
        Bound each dimension without declaring matching prefixes complete
        """
        data = deepcopy(self.data)
        parameters = data["phase"][0]["constitutive_model"]["elastic_parameters"]
        parameters["series"] = list(range(40))
        parameters["long"] = "x" * 700
        nested = parameters
        for _ in range(35):
            nested["deeper"] = {}
            nested = nested["deeper"]
        for obj in (self.first, self.public):
            obj.data = data
            obj.save(update_fields=["data"])
        context = self.inspect()
        self.assertTrue(context["limited"])
        self.assertEqual(context["limits"]["omitted_array_entries"], 16)
        self.assertGreater(context["limits"]["depth_limits"], 0)
        self.assertGreater(context["limits"]["shortened_values"], 0)
        self.assertLessEqual(len(context["rows"]), 300)
        series = self.rows(context)["phase[0].constitutive_model.elastic_parameters.series[0]"]
        self.assertEqual(series["status"], "incomplete")
        self.assertTrue(all(len(cell["value"]) <= 512 for row in context["rows"] for cell in row["cells"]))
        with patch("apps.pages.study_details.MAX_PARAMETER_ROWS", 5):
            bounded = self.inspect()
        self.assertEqual(len(bounded["rows"]), 5)
        self.assertGreater(bounded["limits"]["omitted_rows"], 0)
        self.assertLessEqual(len(bounded["differences"]), 8)

    def test_node_budget_is_shared_across_the_complete_selection(self):
        """
        Stop total traversal work and mark unvisited record content explicitly
        """
        with patch("apps.pages.study_details.MAX_VISITED_NODES", 40):
            context = self.inspect()
        self.assertTrue(context["ready"])
        self.assertTrue(context["limited"])
        self.assertLessEqual(context["visited_nodes"], 40)
        self.assertGreater(context["limits"]["node_limits"], 0)
        self.assertGreater(context["counts"]["incomplete"], 0)

    def test_unrelated_phase_arrays_do_not_consume_parameter_coverage(self):
        """
        Keep large orientations outside the requested model and loading traversal
        """
        data = deepcopy(self.data)
        data["phase"][0]["orientation"] = {"supplied_orientations": list(range(2000))}
        self.save_public(data)
        context = self.inspect()
        self.assertFalse(context["limited"])
        self.assertEqual(context["counts"]["incomplete"], 0)
        self.assertFalse(any("orientation" in row["path"] for row in context["rows"]))
        data["Phase"] = deepcopy(data["phase"])
        data["Phase"][0]["orientation"]["supplied_orientations"] = [1]
        self.save_public(data)
        context = self.inspect()
        self.assertEqual(self.rows(context)["phase"]["cells"][1]["state"], "ambiguous")

    def test_ownership_authentication_and_invalid_ids_fail_without_titles(self):
        """
        Reject malformed selection or another owner's workspace before raw access
        """
        for ids in ([], [self.first.pk], [self.first.pk] * 2, [True, self.public.pk], ["1", "2"],
                    [0, self.public.pk], [self.first.pk, 2 ** 64]):
            with self.subTest(ids=ids):
                context = self.inspect(ids)
                self.assertFalse(context["ready"])
                self.assertEqual(context["objects"], [])
                self.assertEqual(context["rows"], [])
        for user in (self.other, AnonymousUser()):
            self.request.user = user
            context = self.inspect()
            self.assertFalse(context["ready"])
            self.assertEqual(context["objects"], [])

    def test_revoked_nonmember_and_hidden_records_reject_every_selected_value(self):
        """
        Avoid partial titles or fields when one selected record is unavailable
        """
        for pk in (self.hidden.pk, 9223372036854775807):
            context = self.inspect([self.first.pk, pk])
            self.assertFalse(context["ready"])
            self.assertEqual(context["objects"], [])
            self.assertNotIn("SECRET", json.dumps(context))
        self.shared.shared_users.clear()
        context = self.inspect([self.first.pk, self.shared.pk])
        self.assertFalse(context["ready"])
        self.assertEqual(context["rows"], [])
        self.collection.members.remove(self.public)
        self.assertEqual(self.inspect()["objects"], [])

    def test_temporary_scope_rechecks_unpinned_members_and_session_binding(self):
        """
        Reject stale complete selections even when their two pinned records survive
        """
        token = create_selection(self.request, [self.first.pk, self.public.pk, self.shared.pk])
        self.assertTrue(self.inspect(selection_token=token)["ready"])
        self.shared.shared_users.clear()
        context = self.inspect(selection_token=token)
        self.assertFalse(context["ready"])
        self.assertEqual(context["objects"], [])
        self.assertEqual(context["rows"], [])
        self.request.session = self.client.session
        self.request.session.cycle_key()
        self.assertFalse(self.inspect(selection_token=token)["ready"])

    def test_temporary_membership_is_read_again_after_selected_locks(self):
        """
        Revalidate a changed complete temporary membership before reading JSON
        """
        token = create_selection(self.request, [self.first.pk, self.public.pk])
        with patch("apps.pages.study_details._selection_ids", side_effect=[
            [self.first.pk, self.public.pk], [self.first.pk, self.public.pk, self.hidden.pk],
        ]), patch("apps.pages.study_details._extract_record", side_effect=AssertionError("raw content inspected")):
            context = self.inspect(selection_token=token)
        self.assertFalse(context["ready"])
        self.assertEqual(context["objects"], [])

    def test_actual_database_bytes_are_checked_before_raw_loading(self):
        """
        Ignore stale declared sizes and return only authorized source links over budget
        """
        JSONData.objects.filter(pk__in=[self.first.pk, self.public.pk]).update(size_bytes=1)
        with patch("apps.pages.study_details.MAX_PARAMETER_BYTES", 10), \
                patch("apps.pages.study_details._extract_record", side_effect=AssertionError("raw content inspected")), \
                CaptureQueriesContext(connection) as queries:
            context = self.inspect()
        self.assertFalse(context["ready"])
        self.assertTrue(context["limited"])
        self.assertIn("16 MiB", context["error"])
        self.assertEqual(context["rows"], [])
        self.assertEqual([obj["title"] for obj in context["objects"]], [f"Object {self.first.pk}", f"Object {self.public.pk}"])
        self.assertTrue(any("parameter_raw_bytes" in query["sql"] for query in queries))
        self.assertFalse(any('"id", "pages_jsondata"."data"' in query["sql"] for query in queries))

    def test_same_freeform_units_are_only_a_recorded_text_match(self):
        """
        Retain unknown supplied unit labels while explaining the comparison scope
        """
        data = deepcopy(self.data)
        data["phase"][0]["constitutive_model"]["units"] = {"custom coefficient": "arbitrary recorded unit"}
        for obj in (self.first, self.public):
            obj.data = data
            obj.save(update_fields=["data"])
        context = self.inspect()
        row = self.rows(context)['phase[0].constitutive_model.units["custom coefficient"]']
        self.assertEqual(row["status"], "same")
        self.assertIn("without mapping or conversion", context["scope_note"])
        self.assertIn("do not establish scientific equivalence", context["scope_note"])
