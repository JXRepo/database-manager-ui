import copy
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.pages.models import JSONData


class ChartsTests(TestCase):
    """
    Verify statistical meaning, exact navigation and access boundaries
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create independent owners without using application data
        """
        cls.viewer = User.objects.create_user(username="chart-viewer")
        cls.other = User.objects.create_user(username="chart-other")

    def setUp(self):
        """
        Authenticate the viewer for each isolated test
        """
        self.client.force_login(self.viewer)

    def create_object(self, identifier="example", owner=None, access="all", **changes):
        """
        Store a small fixture with independently known statistical values

        Parameters
        ----------
        identifier : str
            Supplied object identifier.
        owner : User, optional
            Record owner, defaulting to the viewer.
        access : str
            Stored access type.
        **changes : object
            Top-level metadata replacements.

        Returns
        -------
        JSONData
            Newly stored fixture.
        """
        data = {
            "identifier": identifier,
            "title": "Copper simulation",
            "software": "Abaqus CAE",
            "phase": [{
                "phase_name": "Copper",
                "constitutive_model": {
                    "elastic_model_name": "Anisotropic Elasticity",
                    "plastic_model_name": "Crystal Plasticity",
                },
                "orientation": {"grain_count": 343, "texture_type": "Goss"},
            }],
            "global_temperature": 298,
            "discretization_count": 2744,
            "mechanical_BC": [{"loading_type": "force", "loading_mode": "static"}],
            "units": {"Stress": "MPa", "Strain": 1, "Temperature": "K"},
            "stress": {"stress_33": [0, -100, -150]},
            "total_strain": {"strain_33": [0, -0.01, -0.02]},
            "plastic_strain": {"plastic_strain_33": [0, -0.005, -0.01]},
        }
        data.update(changes)
        return JSONData.objects.create(owner=owner or self.viewer, data=data, access_type=access)

    def dashboard(self, **query):
        """
        Request the real route and require the new statistics contract

        Parameters
        ----------
        **query : str
            GET filters for the page.

        Returns
        -------
        HttpResponse
            Rendered dashboard response.
        """
        response = self.client.get(reverse("charts"), query)
        self.assertEqual(response.status_code, 200)
        self.assertIn("distributions", response.context)
        return response

    def test_public_and_own_scopes_exclude_received_private_records(self):
        """
        Private uploads require an explicit opt-in and shared data stays outside statistics
        """
        own = self.create_object("own", access="c", software="Own solver")
        own_public = self.create_object("own-public", software="Own public solver")
        public = self.create_object("public", owner=self.other, access="all", software="Public solver")
        shared = self.create_object("shared", owner=self.other, access="c", software="Shared solver")
        shared.shared_users.add(self.viewer, self.other)
        self.create_object("hidden", owner=self.other, access="c", software="Secret solver")
        cases = [({}, {own_public.pk, public.pk}),
                 ({"scope": "public", "include_private": "1"}, {own_public.pk, public.pk}),
                 ({"scope": "mine"}, {own_public.pk}),
                 ({"scope": "mine", "include_private": "0"}, {own_public.pk}),
                 ({"scope": "mine", "include_private": "1"}, {own.pk, own_public.pk})]
        for query, ids in cases:
            with self.subTest(query=query):
                response = self.dashboard(**query)
                self.assertEqual(response.context["total_objects"], len(ids))
                self.assertEqual({row["id"] for row in response.context["objects_page"]}, ids)
                self.assertNotContains(response, "Secret solver")
                self.assertNotContains(response, "Shared solver")
                matching = self.client.get(response.context["matching_url"])
                self.assertEqual(matching.context["total_objects"], response.context["matching_count"])
                self.assertEqual({row["id"] for row in matching.context["objects_page"]}, ids)
                for row in response.context["categories"]["software"]["rows"]:
                    selected = self.client.get(row["url"])
                    self.assertEqual(selected.context["total_objects"], row["count"])
                    self.assertTrue({item["id"] for item in selected.context["objects_page"]} <= ids)
        self.assertEqual(self.dashboard(software="Secret solver").context["total_objects"], 0)
        self.assertEqual(self.dashboard(software="Own solver").context["total_objects"], 0)
        self.assertEqual(self.dashboard(scope="mine", include_private="1", software="Shared solver").context["total_objects"], 0)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("charts")).status_code, 302)

    def test_multiple_phases_and_descriptions_count_each_object_once(self):
        """
        Repeated labels never inflate category counts or distinct phase totals
        """
        obj = self.create_object(software=[" Abaqus CAE ", "abaqus cae", "DAMASK"])
        phase = obj.data["phase"][0]
        obj.data["phase"] = [phase, copy.deepcopy(phase), {"phase_name": "Nickel"}]
        obj.save()
        self.create_object("two", software="ABAQUS CAE")
        response = self.dashboard()
        phases = {row["label"]: row["count"] for row in response.context["categories"]["phase"]["rows"]}
        software = {row["label"].casefold(): row["count"] for row in response.context["categories"]["software"]["rows"]}
        self.assertEqual(phases, {"Copper": 2, "Nickel": 1})
        self.assertEqual({row["label"]: row["percent"] for row in response.context["categories"]["phase"]["rows"]},
                         {"Copper": 100, "Nickel": 50})
        self.assertEqual(software, {"abaqus cae": 2, "damask": 1})
        self.assertEqual(response.context["phase_count"], 2)

    def test_category_filters_match_exact_names_on_the_same_object(self):
        """
        Combined conditions cannot match fragments or different records
        """
        wanted = self.create_object("wanted")
        self.create_object("other-software", software="DAMASK")
        self.create_object("other-phase", phase=[{"phase_name": "Copper oxide"}])
        response = self.dashboard(phase=" copper ", software="ABAQUS CAE")
        self.assertEqual([row["id"] for row in response.context["objects_page"]], [wanted.pk])
        self.assertEqual(self.dashboard(phase="Copper", software="aba").context["total_objects"], 0)
        for chip in response.context["active_filters"]:
            query = parse_qs(urlsplit(chip["url"]).query)
            self.assertEqual(len(set(query) & {"phase", "software"}), 1)

    def test_schema_spellings_wrappers_and_original_values_are_preserved(self):
        """
        Charts use the same recognized metadata as upload and detail
        """
        obj = self.create_object()
        raw = copy.deepcopy(obj.data)
        raw["Phase"] = raw.pop("phase")
        raw["Software used"] = raw.pop("software")
        raw["Global Temperature"] = [["298"]]
        del raw["global_temperature"]
        raw["Stress"] = {"Stress 33": ["0", "-100", "-150"]}
        del raw["stress"]
        raw["Total Strain"] = {"Strain 33": ["0", "-0.01", "-0.02"]}
        del raw["total_strain"]
        obj.data = raw
        obj.save()
        response = self.dashboard()
        self.assertEqual(response.context["matching_count"], 1)
        self.assertEqual(response.context["distributions"][0]["median"], "298")
        self.assertEqual(response.context["categories"]["software"]["rows"][0]["count"], 1)
        obj.refresh_from_db()
        self.assertEqual(obj.data, raw)

    def test_phase_names_prefer_current_names_and_retain_legacy_fallbacks(self):
        """
        Identifiers are not guessed to be material names
        """
        self.create_object(phase=[{"phase_name": "Copper", "phase_identifier": "Old copper"},
                                  {"phase_identifier": "Legacy nickel"}, {"phase_id": 42}])
        response = self.dashboard()
        self.assertEqual({row["label"] for row in response.context["categories"]["phase"]["rows"]},
                         {"Copper", "Legacy nickel"})

    def test_temperatures_convert_explicit_units_before_aggregation(self):
        """
        Physically identical temperatures share the same value and bin
        """
        self.create_object("kelvin")
        self.create_object("celsius", global_temperature=24.85, units={"Temperature": "Celsius"})
        self.create_object("fahrenheit", global_temperature=76.73, units={"Temperature": "Fahrenheit"})
        response = self.dashboard()
        temperature = response.context["distributions"][0]
        self.assertEqual((temperature["minimum"], temperature["maximum"], temperature["median"]),
                         ("298", "298", "298"))
        self.assertEqual(temperature["observation_count"], 3)
        self.assertEqual(len(temperature["bins"]), 1)
        selected = self.client.get(temperature["bins"][0]["url"])
        self.assertEqual(selected.context["total_objects"], 3)

    def test_invalid_temperatures_and_count_values_are_excluded_not_zero(self):
        """
        Missing units, impossible temperatures and booleans cannot become observations
        """
        for index, (value, unit) in enumerate([(298, None), (298, "unknown"), (-1, "K"),
                                               (True, "K"), ("bad", "K"), (None, "K")]):
            self.create_object(str(index), global_temperature=value,
                               units={"Temperature": unit}, discretization_count=True,
                               phase=[{"phase_name": "Copper", "orientation": {"grain_count": False}}])
        response = self.dashboard()
        for distribution in response.context["distributions"]:
            self.assertEqual(distribution["observation_count"], 0)
            self.assertEqual(distribution["bins"], [])
            self.assertEqual(distribution["excluded_objects"], 6)

    def test_grains_are_phase_observations_and_bins_link_to_distinct_objects(self):
        """
        Phase counts stay separate from the number of linked objects
        """
        obj = self.create_object(phase=[
            {"phase_name": "Copper", "orientation": {"grain_count": 10}},
            {"phase_name": "Nickel", "orientation": {"grain_count": 10}},
            {"phase_name": "Iron", "orientation": {"grain_number": "30"}},
        ])
        response = self.dashboard()
        grains = response.context["distributions"][1]
        self.assertEqual(grains["observation_count"], 3)
        self.assertEqual(grains["object_count"], 1)
        self.assertEqual(grains["median"], "10")
        self.assertFalse(grains["constant"])
        self.assertEqual(grains["bins"][0]["count"], 2)
        self.assertEqual(grains["bins"][0]["object_count"], 1)
        selected = self.client.get(grains["bins"][0]["url"])
        self.assertEqual([row["id"] for row in selected.context["objects_page"]], [obj.pk])

    def test_histogram_boundaries_do_not_drop_or_double_count_values(self):
        """
        Every observation belongs to exactly one displayed numeric bin
        """
        for index in range(21):
            self.create_object(str(index), global_temperature=index * 10)
        response = self.dashboard()
        bins = response.context["distributions"][0]["bins"]
        self.assertLessEqual(len(bins), 8)
        self.assertEqual(sum(item["count"] for item in bins), 21)
        seen = set()
        for item in bins:
            selected = self.client.get(item["url"])
            ids = {row["id"] for row in selected.context["objects_page"]}
            self.assertEqual(selected.context["total_objects"], item["count"])
            self.assertFalse(seen & ids)
            seen.update(ids)
        self.assertEqual(len(seen), 21)

    def test_invalid_filters_never_broaden_the_selection(self):
        """
        Malformed scope, result and numeric filters return errors and no records
        """
        self.create_object()
        cases = [{"scope": "everyone"}, {"result": "secret"}, {"note": "unknown"},
                 {"measure": "temperature", "lo": "NaN", "hi": "400"},
                 {"measure": "temperature", "lo": "400", "hi": "100"},
                 {"lo": "10"}, {"measure": "unknown", "lo": "1", "hi": "2"},
                 {"measure": "temperature", "lo": "1", "hi": "2", "inclusive": "maybe"},
                 {"range": ""}, {"range": "bad"}, {"range": "temperature:1:2:maybe"},
                 {"scope": ["mine", "all"]}, {"group": "unknown"}, {"component": "fake"},
                 {"include_private": "yes"}, {"include_private": ""}, {"include_private": ["0", "1"]},
                 {"coverage": "unknown"}, {"coverage": ""},
                 {"material_group": "software"}, {"material_group": ["phase", "texture"]},
                 {"group": ["software", "loading_mode"]},
                 {"curve": "-1"}, {"curve": "1e2"}, {"curve": "1" * 5000}]
        for query in cases:
            with self.subTest(query=query):
                response = self.dashboard(**query)
                self.assertTrue(response.context["filter_errors"])
                self.assertEqual(response.context["total_objects"], 0)

    def test_removing_a_valid_range_preserves_other_invalid_conditions(self):
        """
        A removal link deletes its own interval even after a malformed parameter
        """
        self.create_object()
        response = self.dashboard(range=["bad", "temperature:298:298:1", "grain_count:343:343:1"])
        for index, chip in enumerate(response.context["active_filters"]):
            query = parse_qs(urlsplit(chip["url"]).query)
            self.assertEqual(query["range"][0], "bad")
            self.assertNotIn(("temperature:298:298:1", "grain_count:343:343:1")[index], query["range"])
            selected = self.client.get(chip["url"])
            self.assertTrue(selected.context["filter_errors"])
            self.assertEqual(selected.context["total_objects"], 0)

    def test_successive_chart_selections_refine_the_same_objects(self):
        """
        Co-occurring labels and phase counts retain all earlier conditions
        """
        wanted = self.create_object("wanted", phase=[
            {"phase_name": "Copper", "orientation": {"grain_count": 10}},
            {"phase_name": "Nickel", "orientation": {"grain_count": 30}},
        ])
        self.create_object("other", global_temperature=500,
                           phase=[{"phase_name": "Nickel", "orientation": {"grain_count": 30}}])
        response = self.dashboard(phase="Copper")
        nickel = next(row for row in response.context["categories"]["phase"]["rows"] if row["label"] == "Nickel")
        selected = self.client.get(nickel["url"])
        self.assertEqual(selected.context["total_objects"], nickel["count"])
        self.assertEqual(len(selected.context["active_filters"]), 2)
        for chip in selected.context["active_filters"]:
            self.assertEqual(len(parse_qs(urlsplit(chip["url"]).query)["phase"]), 1)
        response = self.dashboard(measure="temperature", lo="298", hi="298")
        for value in ("10", "30"):
            grains = response.context["distributions"][1]
            bucket = next(item for item in grains["bins"]
                          if Decimal(item["low"]) <= Decimal(value) <= Decimal(item["high"]))
            response = self.client.get(bucket["url"])
            self.assertEqual(response.context["total_objects"], bucket["object_count"])
            self.assertEqual([row["id"] for row in response.context["objects_page"]], [wanted.pk])
        self.assertEqual(len(response.context["active_filters"]), 3)

    def test_result_and_note_selections_keep_previous_conditions(self):
        """
        Selecting another availability flag never adds records outside the selection
        """
        self.create_object("both", stress={"stress_33": [0]}, units={})
        self.create_object("strain-only", stress={}, units={})
        self.create_object("lengths-only", stress={"stress_33": [0]})
        response = self.dashboard(result="stress", note="result_units")
        for key, rows in (("total_strain", response.context["result_rows"]),
                          ("unequal_lengths", response.context["note_rows"])):
            row = next(item for item in rows if item["key"] == key)
            selected = self.client.get(row["url"])
            self.assertEqual(selected.context["total_objects"], row["count"])
            self.assertEqual(selected.context["total_objects"], 1)

    def test_fahrenheit_bins_preserve_high_precision_extrema(self):
        """
        Repeating decimal conversions cannot fall outside rounded bin boundaries
        """
        for value in range(1, 10):
            self.create_object(str(value), global_temperature=value, units={"Temperature": "F"})
        response = self.dashboard()
        distribution = response.context["distributions"][0]
        self.assertEqual(sum(item["count"] for item in distribution["bins"]), 9)
        for bucket in distribution["bins"]:
            selected = self.client.get(bucket["url"])
            self.assertEqual(selected.context["total_objects"], bucket["count"])

    def test_close_temperatures_keep_distinct_visible_bounds(self):
        """
        Formatting cannot collapse different intervals into identical labels
        """
        for index in range(9):
            self.create_object(str(index), global_temperature=298 + index / 100000000)
        response = self.dashboard()
        distribution = response.context["distributions"][0]
        self.assertNotEqual(distribution["minimum"], distribution["maximum"])
        self.assertEqual(len({item["label"] for item in distribution["bins"]}), 8)
        columns = response.context["histogram"]["columns"]
        self.assertEqual(len({(item["low_label"], item["high_label"]) for item in columns}), 8)
        for item in columns:
            self.assertNotEqual(item["low_label"], item["high_label"])

    def test_grain_aliases_unwrap_scalars_and_reject_every_conflicting_spelling(self):
        """
        Grain number aliases follow scalar wrapper and conflict rules
        """
        for index, orientation in enumerate([
            {"grain_number": [["10"]]}, {"grain_number": 10, "Grain Number": 30},
            {"grain_count": 10, "Grain Number": "10"},
            {"grain_count": 10, "Grain Number": 30},
        ]):
            self.create_object(str(index), phase=[{"phase_name": "Copper", "orientation": orientation}])
        response = self.dashboard()
        grains = response.context["distributions"][1]
        self.assertEqual(grains["observation_count"], 2)
        self.assertEqual(grains["minimum"], "10")
        self.assertEqual(grains["maximum"], "10")
        notes = {row["key"]: row["count"] for row in response.context["note_rows"]}
        self.assertEqual(notes["grain_conflicts"], 2)

    def test_non_11_and_equivalent_only_results_are_counted(self):
        """
        Mechanical availability recognizes components and supplied equivalent arrays
        """
        self.create_object("component-33")
        self.create_object("equivalents", stress={"equivalent_stress": [0, 100]},
                           total_strain={"equivalent_strain": [0, 0.1]}, plastic_strain={})
        response = self.dashboard()
        counts = {row["key"]: row["count"] for row in response.context["result_rows"]}
        self.assertEqual(response.context["matching_count"], 2)
        self.assertEqual(counts["stress"], 2)
        self.assertEqual(counts["plastic_strain"], 1)
        self.assertEqual(counts["supplied_equivalent"], 1)
        self.assertEqual(counts["calculated_equivalent"], 0)

    def test_calculated_equivalents_respect_explicit_empty_fields(self):
        """
        Derivation is possible only for absent fields with all required components
        """
        stress = {f"stress_{key}": [0, 1] for key in ("11", "22", "33", "12", "13", "23")}
        self.create_object("derived", stress=stress)
        self.create_object("explicit-empty", stress={**stress, "equivalent_stress": []})
        response = self.dashboard(result="calculated_equivalent")
        self.assertEqual(response.context["total_objects"], 1)
        self.assertEqual(response.context["objects_page"][0]["identifier"], "derived")

    def test_length_and_unit_notes_do_not_label_objects_invalid(self):
        """
        Different curve lengths remain inspectable with precise availability notes
        """
        obj = self.create_object(stress={"stress_33": [0, 1], "stress_23": [0]}, units={})
        response = self.dashboard()
        counts = {row["key"]: row["count"] for row in response.context["note_rows"]}
        self.assertEqual(counts["unequal_lengths"], 1)
        self.assertEqual(counts["result_units"], 1)
        self.assertEqual(response.context["matching_count"], 1)
        notes = [row for row in response.context["note_rows"] if row["key"] == "unequal_lengths"]
        selected = self.client.get(notes[0]["url"])
        self.assertEqual(selected.context["objects_page"][0]["id"], obj.pk)
        self.assertNotContains(response, "Comparable")

    def test_boolean_or_malformed_arrays_do_not_count_as_results(self):
        """
        Only finite numeric mechanical arrays contribute to availability
        """
        self.create_object(stress={"stress_11": [False, True], "stress_22": ["NaN", 1]},
                           total_strain={"strain_11": [0, None]}, plastic_strain={})
        response = self.dashboard()
        self.assertEqual(response.context["matching_count"], 0)
        counts = {row["key"]: row["count"] for row in response.context["result_rows"]}
        self.assertEqual(counts["stress"], 0)
        self.assertEqual(counts["total_strain"], 0)

    def test_conflicting_functional_aliases_do_not_select_a_value(self):
        """
        Legacy conflicts remain accessible but do not drive statistics
        """
        self.create_object(**{"Global Temperature": 500})
        response = self.dashboard()
        self.assertEqual(response.context["total_objects"], 1)
        self.assertEqual(response.context["distributions"][0]["observation_count"], 0)
        notes = {row["key"]: row["count"] for row in response.context["note_rows"]}
        self.assertEqual(notes["conflicting_metadata"], 1)

    def test_long_and_hostile_labels_are_escaped_and_all_categories_remain_available(self):
        """
        Uploaded labels cannot inject HTML and category limits never discard counts
        """
        hostile = '<img src=x onerror="alert(1)">'
        for index in range(12):
            self.create_object(str(index), software=hostile if index == 0 else f"Software {index}")
        response = self.dashboard(group="software")
        self.assertEqual(len(response.context["categories"]["software"]["rows"]), 12)
        self.assertNotContains(response, hostile)
        self.assertContains(response, "&lt;img")
        self.assertEqual(response.context["total_objects"], 12)

    def test_pagination_keeps_filters_and_all_matching_objects(self):
        """
        Every selected record remains reachable without changing its statistical scope
        """
        for index in range(25):
            self.create_object(str(index))
        response = self.dashboard(phase="Copper", scope="mine")
        page = response.context["objects_page"]
        self.assertEqual(page.paginator.count, 25)
        self.assertLess(len(page), 25)
        next_url = response.context["next_url"]
        query = parse_qs(urlsplit(next_url).query)
        self.assertEqual(query["phase"], ["Copper"])
        self.assertEqual(query["scope"], ["mine"])
        second = self.client.get(next_url)
        self.assertFalse({row["id"] for row in page} & {row["id"] for row in second.context["objects_page"]})
        self.assertEqual(second.context["total_objects"], 25)

    def test_empty_scope_keeps_controls_without_nan_or_phantom_categories(self):
        """
        Empty data remains a useful starting point with no fabricated percentages
        """
        response = self.dashboard()
        self.assertEqual(response.context["total_objects"], 0)
        self.assertEqual(response.context["phase_count"], 0)
        self.assertContains(response, 'name="scope"')
        self.assertNotContains(response, "NaN")
        self.assertNotContains(response, "0 / 0")
        self.assertTrue(all(not group["rows"] for group in response.context["categories"].values()))

    def test_material_and_setup_preferences_are_independent(self):
        """
        Materials and simulation setup expose separate aggregate selections
        """
        self.create_object()
        response = self.dashboard()
        self.assertEqual(response.context["material_group"], "phase")
        self.assertEqual(response.context["material_category"]["rows"][0]["label"], "Copper")
        self.assertEqual(response.context["group"], "software")
        self.assertEqual(response.context["selected_category"]["rows"][0]["label"], "Abaqus CAE")
        self.assertEqual(dict(response.context["material_options"]), {"phase": "Phase", "texture": "Texture"})
        self.assertEqual(set(dict(response.context["group_options"])),
                         {"software", "elastic_model", "plastic_model", "loading_type", "loading_mode"})
        selected = self.dashboard(material_group="texture", group="loading_mode")
        self.assertEqual(selected.context["material_category"]["rows"][0]["label"], "Goss")
        self.assertEqual(selected.context["material_plot"]["rows"][0]["count"], 1)
        self.assertEqual(selected.context["selected_category"]["rows"][0]["label"], "static")
        self.assertEqual(selected.context["category_plot"]["rows"][0]["count"], 1)
        for category in (selected.context["material_category"], selected.context["selected_category"]):
            row = category["rows"][0]
            drilled = self.client.get(row["url"])
            self.assertEqual(drilled.context["total_objects"], row["count"])
            self.assertEqual(drilled.context["material_group"], "texture")
            self.assertEqual(drilled.context["group"], "loading_mode")

    def test_legacy_category_preferences_map_to_materials(self):
        """
        Existing phase and texture bookmarks remain usable with the new panels
        """
        self.create_object()
        for group in ("phase", "texture"):
            with self.subTest(group=group):
                response = self.dashboard(group=group)
                self.assertFalse(response.context["filter_errors"])
                self.assertEqual(response.context["material_group"], group)
                self.assertEqual(response.context["group"], "software")
        response = self.dashboard(group="texture", material_group="phase")
        self.assertEqual(response.context["material_group"], "phase")
        self.assertEqual(response.context["group"], "software")

    def test_panel_controls_keep_filters_and_other_preferences(self):
        """
        Changing a visible aggregate never drops active conditions or scope
        """
        self.create_object(software=["Abaqus CAE", "DAMASK"])
        query = {
            "scope": "mine", "include_private": "1", "phase": "Copper", "software": ["Abaqus CAE", "DAMASK"],
            "result": ["stress", "matching_response"], "range": ["temperature:298:298:1", "grain_count:343:343:1"],
            "coverage": "matching",
            "material_group": "texture", "group": "loading_mode", "measure": "grain_count",
            "curve": "999", "component": "33", "show": "objects", "page": "2",
        }
        response = self.dashboard(**query)
        self.assertEqual(response.context["total_objects"], 1)
        self.assertEqual(len(response.context["active_filters"]), 8)
        for control in ("material_group", "group", "measure"):
            params = response.context["control_params"][control]
            for key in ("scope", "include_private", "phase", "software", "result", "range", "coverage"):
                expected = query[key] if isinstance(query[key], list) else [query[key]]
                self.assertEqual([value for name, value in params if name == key], expected)
            for key in {"material_group", "group", "measure"} - {control}:
                self.assertIn((key, query[key]), params)
            self.assertFalse({control, "curve", "component", "show", "page"} & {key for key, _value in params})
        self.assertEqual(dict(response.context["control_params"]["scope"]),
                         {"material_group": "texture", "group": "loading_mode", "measure": "grain_count"})

    def test_matching_components_count_real_pairs_and_preserve_legacy_groups(self):
        """
        Availability distinguishes matching components from two unrelated groups
        """
        direct = self.create_object("matching-33")
        self.create_object("unmatched", stress={"stress_11": [0, 1]}, total_strain={"strain_33": [0, .1]})
        supplied = self.create_object("supplied", stress={"equivalent_stress": [8, 9]},
                                      total_strain={"equivalent_strain": [1, 2]})
        stress = {f"stress_{key}": [0, 1] for key in ("11", "22", "33", "12", "13", "23")}
        strain = {f"strain_{key}": [0, .01] for key in ("11", "22", "33", "12", "13", "23")}
        calculated = self.create_object("calculated", stress=stress, total_strain=strain)
        mixed = self.create_object("mixed", stress=stress, total_strain={"equivalent_strain": [0, .01]})
        self.create_object("explicit-empty", stress={**stress, "equivalent_stress": []},
                           total_strain={"equivalent_strain": [0, .01]})
        response = self.dashboard()
        self.assertEqual(response.context["matching_count"], 4)
        self.assertEqual({row["key"] for row in response.context["output_rows"]},
                         {"stress", "total_strain", "plastic_strain", "supplied_equivalent", "calculated_equivalent"})
        row = next(item for item in response.context["result_rows"] if item["key"] == "matching_response")
        self.assertEqual(row["count"], 4)
        selected = self.client.get(response.context["matching_url"])
        self.assertEqual({item["id"] for item in selected.context["objects_page"]},
                         {direct.pk, supplied.pk, calculated.pk, mixed.pk})
        self.assertEqual(self.dashboard(result="paired").context["total_objects"], 6)
        legacy = self.dashboard(result=["paired", "matching_response"])
        self.assertEqual(legacy.context["total_objects"], 4)
        for obj in (supplied, calculated, mixed):
            original = copy.deepcopy(obj.data)
            obj.refresh_from_db()
            self.assertEqual(obj.data, original)

    def test_legacy_curve_preferences_never_add_preview_or_escape_filters(self):
        """
        Old object selectors remain harmless after removing the duplicate curve
        """
        copper = self.create_object(stress={"stress_33": [0, 100, 40, -60]},
                                     total_strain={"strain_33": [0, .03, .01, -.02]})
        nickel = self.create_object("nickel", phase=[{"phase_name": "Nickel"}])
        hidden = self.create_object("hidden-curve", owner=self.other, access="c", stress={"stress_33": [0, 9876543]})
        for curve in (copper.pk, hidden.pk):
            response = self.dashboard(phase="Nickel", curve=str(curve), component="33")
            self.assertEqual([row["id"] for row in response.context["objects_page"]], [nickel.pk])
            self.assertNotIn("curve", response.context)
            self.assertNotIn("curve_objects", response.context)
            self.assertNotContains(response, "charts-curve-svg")
            self.assertNotContains(response, "9876543")
            self.assertNotContains(response, "hidden-curve")
            row = response.context["material_category"]["rows"][0]
            self.assertNotIn("curve", parse_qs(urlsplit(row["url"]).query))

    def test_result_coverage_preserves_large_arrays_and_original_precision(self):
        """
        Statistical summaries never reduce or rewrite source mechanical arrays
        """
        values = [10 ** 50 + index for index in range(12000)]
        obj = self.create_object(stress={"stress_33": values},
                                 total_strain={"strain_33": list(range(12002))})
        original = copy.deepcopy(obj.data)
        response = self.dashboard(result="matching_response")
        self.assertEqual(response.context["matching_count"], 1)
        self.assertEqual(response.context["objects_page"][0]["points"], "3–12,002 points")
        self.assertNotIn("curve", response.context)
        self.assertNotContains(response, str(values[0]))
        notes = {row["key"]: row["count"] for row in response.context["note_rows"]}
        self.assertEqual(notes["unequal_lengths"], 1)
        obj.refresh_from_db()
        self.assertEqual(obj.data, original)

    def test_legacy_scopes_redirect_to_public_without_private_flag(self):
        """
        Old broad scopes cannot reintroduce owned or received private data
        """
        public = self.create_object("public")
        self.create_object("private", access="c")
        for scope in ("all", "shared"):
            response = self.client.get(reverse("charts"), {
                "scope": scope, "include_private": "1", "phase": "Copper", "result": "stress",
                "coverage": "matching", "group": "loading_mode", "material_group": "texture",
                "measure": "grain_count", "range": ["temperature:298:298:1", "grain_count:343:343:1"],
            })
            self.assertEqual(response.status_code, 302)
            query = parse_qs(urlsplit(response["Location"]).query)
            self.assertEqual(query["scope"], ["public"])
            self.assertNotIn("include_private", query)
            self.assertEqual(query["coverage"], ["matching"])
            self.assertEqual(query["range"], ["temperature:298:298:1", "grain_count:343:343:1"])
            self.assertEqual(query["phase"], ["Copper"])
            self.assertEqual(query["material_group"], ["texture"])
            self.assertEqual(query["group"], ["loading_mode"])
            selected = self.client.get(response["Location"])
            self.assertEqual([row["id"] for row in selected.context["objects_page"]], [public.pk])
        for query in ({"scope": "all", "include_private": "yes"},
                      {"scope": "shared", "result": "unknown"}, {"scope": ["all", "shared"]}):
            response = self.dashboard(**query)
            self.assertTrue(response.context["filter_errors"])
            self.assertEqual(response.context["total_objects"], 0)

    def test_private_opt_in_survives_filter_links_clear_and_pagination(self):
        """
        Own private statistics stay explicitly scoped throughout chart navigation
        """
        for index in range(12):
            self.create_object(str(index), access="c")
        self.create_object("other-public", owner=self.other)
        query = {"scope": "mine", "include_private": "1", "phase": "Copper"}
        response = self.dashboard(**query)
        self.assertEqual(response.context["total_objects"], 12)
        self.assertTrue(response.context["include_private"])
        self.assertEqual(response.context["base_count"], 12)
        self.assertEqual(parse_qs(urlsplit(response.context["clear_url"]).query),
                         {"scope": ["mine"], "include_private": ["1"]})
        urls = [response.context["next_url"], response.context["matching_url"],
                response.context["material_category"]["rows"][0]["url"],
                response.context["coverage_rows"][0]["url"]]
        for url in urls:
            params = parse_qs(urlsplit(url).query)
            self.assertEqual(params["scope"], ["mine"])
            self.assertEqual(params["include_private"], ["1"])
            selected = self.client.get(url)
            self.assertEqual(selected.context["total_objects"], 12)
            self.assertTrue(all(row["identifier"] != "other-public" for row in selected.context["objects_page"]))
        self.assertEqual(self.dashboard(scope="mine").context["total_objects"], 0)

    def test_coverage_pie_is_exhaustive_and_links_preserve_the_selection(self):
        """
        Every selected object belongs to exactly one stress–strain coverage slice
        """
        matched = self.create_object("matched")
        equivalent = self.create_object("equivalent", stress={"equivalent_stress": [0, 1]},
                                         total_strain={"equivalent_strain": [0, .1]})
        unmatched = self.create_object("unmatched", stress={"stress_11": [0, 1]},
                                        total_strain={"strain_33": [0, .1]})
        absent = self.create_object("absent", stress={}, total_strain={}, plastic_strain={})
        conflict = self.create_object("conflict", **{"Global Temperature": 400})
        originals = {obj.pk: copy.deepcopy(obj.data) for obj in (matched, equivalent, unmatched, absent, conflict)}
        response = self.dashboard(scope="mine", software="Abaqus CAE", material_group="texture")
        rows = {row["key"]: row for row in response.context["coverage_rows"]}
        self.assertEqual((rows["matching"]["count"], rows["without_matching"]["count"]), (2, 2))
        self.assertEqual(sum(row["count"] for row in rows.values()), response.context["total_objects"])
        self.assertEqual(sum(row["percent"] for row in rows.values()), 100)
        for key, ids in (("matching", {matched.pk, equivalent.pk}), ("without_matching", {unmatched.pk, absent.pk})):
            row = rows[key]
            selected = self.client.get(row["url"])
            self.assertEqual(selected.context["total_objects"], row["count"])
            self.assertEqual({item["id"] for item in selected.context["objects_page"]}, ids)
            params = parse_qs(urlsplit(row["url"]).query)
            self.assertEqual(params["software"], ["Abaqus CAE"])
            self.assertEqual(params["material_group"], ["texture"])
            self.assertEqual(params["scope"], ["mine"])
            self.assertEqual(len(selected.context["coverage_plot"]["slices"]), 1)
            self.assertTrue(selected.context["coverage_plot"]["slices"][0]["full_circle"])
        self.assertEqual(len(response.context["coverage_plot"]["slices"]), 2)
        self.assertTrue(all(not item["full_circle"] for item in response.context["coverage_plot"]["slices"]))
        self.assertEqual(self.dashboard().context["total_objects"], 5)
        self.assertEqual(self.dashboard().context["coverage_rows"][1]["count"], 3)
        empty = self.dashboard(coverage=["matching", "without_matching"])
        self.assertFalse(empty.context["filter_errors"])
        self.assertEqual(empty.context["total_objects"], 0)
        self.assertEqual(empty.context["coverage_plot"]["slices"], [])
        self.assertEqual(empty.context["coverage_plot"]["total"], 0)
        for obj in (matched, equivalent, unmatched, absent, conflict):
            obj.refresh_from_db()
            self.assertEqual(obj.data, originals[obj.pk])
        without = self.dashboard(coverage="without_matching")
        absent_row = next(row for row in without.context["objects_page"] if row["id"] == absent.pk)
        self.assertEqual(absent_row["result_label"], "No mechanical results")

    def test_histogram_uses_equal_width_intervals_and_retains_empty_bins(self):
        """
        Widely separated values occupy numeric intervals rather than category slots
        """
        for value in (1, 2, 100):
            self.create_object(str(value), global_temperature=value)
        response = self.dashboard()
        distribution = response.context["distributions"][0]
        self.assertFalse(distribution["constant"])
        self.assertEqual([bucket["count"] for bucket in distribution["bins"]], [2, 0, 1])
        self.assertEqual({Decimal(bucket["high"]) - Decimal(bucket["low"]) for bucket in distribution["bins"]},
                         {Decimal(33)})
        self.assertEqual([bucket["inclusive"] for bucket in distribution["bins"]], [False, False, True])
        columns = response.context["histogram"]["columns"]
        self.assertAlmostEqual(columns[0]["width"], 574 / 3 - 1, places=2)
        self.assertEqual(columns[1]["plot_height"], 0)
        for bucket in distribution["bins"]:
            selected = self.client.get(bucket["url"])
            self.assertEqual(selected.context["total_objects"], bucket["object_count"])

    def test_constant_histogram_and_empty_pie_never_invent_observations(self):
        """
        Empty and identical values remain factual special cases for statistical charts
        """
        empty = self.dashboard()
        self.assertEqual(empty.context["coverage_plot"]["total"], 0)
        self.assertEqual(empty.context["coverage_plot"]["slices"], [])
        self.create_object()
        self.create_object("same-temperature")
        response = self.dashboard()
        distribution = response.context["distributions"][0]
        self.assertTrue(distribution["constant"])
        self.assertEqual(len(distribution["bins"]), 1)
        self.assertEqual(distribution["bins"][0]["low"], "298")
        self.assertEqual(distribution["bins"][0]["high"], "298")
        self.assertEqual(distribution["bins"][0]["count"], 2)
        self.assertEqual(response.context["histogram"]["columns"][0]["width"], 108)
        self.assertEqual(len(response.context["coverage_plot"]["slices"]), 1)
        self.assertTrue(response.context["coverage_plot"]["slices"][0]["full_circle"])

    def test_large_neighboring_counts_keep_exact_extrema_and_readable_offsets(self):
        """
        Large integer baselines never erase small differences in histogram tables
        """
        baseline = 10 ** 50
        objects = [self.create_object(str(index), discretization_count=baseline + index) for index in range(3)]
        response = self.dashboard(measure="discretization_count")
        item = response.context["selected_distribution"]
        self.assertEqual(tuple(Decimal(item[key]) for key in ("minimum", "maximum", "median")),
                         (baseline, baseline + 2, baseline + 1))
        self.assertEqual(item["offset"], "+1e+50")
        self.assertEqual(len({bucket["label"] for bucket in item["bins"]}), 3)
        self.assertEqual(Decimal(item["bins"][0]["low"]), baseline)
        self.assertEqual(Decimal(item["bins"][-1]["high"]), baseline + 2)
        self.assertEqual(sum(bucket["count"] for bucket in item["bins"]), 3)
        columns = response.context["histogram"]["columns"]
        self.assertEqual(columns[0]["low_label"], "0")
        self.assertEqual(columns[-1]["high_label"], "2")
        self.assertEqual(len({(column["low_label"], column["high_label"]) for column in columns}), 3)
        self.assertTrue(all(len(column["low_label"]) < 20 for column in columns))
        for bucket in item["bins"]:
            selected = self.client.get(bucket["url"])
            self.assertEqual(selected.context["total_objects"], bucket["object_count"])
        for index, obj in enumerate(objects):
            obj.refresh_from_db()
            self.assertEqual(obj.data["discretization_count"], baseline + index)

    def test_even_median_preserves_half_steps_above_large_integer_baselines(self):
        """
        Decimal averaging retains fractional medians beyond the default precision
        """
        baseline = 10 ** 50
        self.create_object("first", discretization_count=baseline)
        self.create_object("second", discretization_count=baseline + 1)
        response = self.dashboard(measure="discretization_count")
        item = response.context["selected_distribution"]
        self.assertEqual(item["median"], f"{baseline}.5")
        self.assertEqual(Decimal(item["minimum"]), baseline)
        self.assertEqual(Decimal(item["maximum"]), baseline + 1)
        self.assertEqual(item["offset"], "+1e+50")
        self.assertEqual(response.context["histogram"]["columns"][0]["high_label"], "0.5")
        self.assertEqual(sum(bucket["count"] for bucket in item["bins"]), 2)
