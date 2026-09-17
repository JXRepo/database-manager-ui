import json
import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.test.html import parse_html
from django.urls import reverse

from .models import JSONData


def _html_elements(element):
    """
    Traverse rendered elements outside inert HTML templates

    This keeps condition row templates out of active form assertions.

    Parameters
    ----------
    element : django.test.html.Element
        Parsed HTML element to traverse.

    Yields
    ------
    django.test.html.Element
        Active elements in document order.
    """
    if isinstance(element, str) or element.name == "template":
        return
    yield element
    for child in element.children:
        yield from _html_elements(child)


class AdvancedSearchTests(TestCase):
    """
    Exercise field conditions and access boundaries through the search page
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create public, owned, shared, and inaccessible records
        """
        cls.viewer = User.objects.create_user(username="search_viewer")
        cls.other = User.objects.create_user(username="other_owner")
        cls.own = JSONData.objects.create(
            owner=cls.viewer,
            access_type="c",
            data={
                "identifier": "own-copper",
                "title": "Copper tensile experiment",
                "creator": ["Ronak Shoghi"],
                "creator_affiliation": ["ICAMS"],
                "software": "Abaqus CAE",
                "keywords": ["crystal", "plasticity"],
                "phase": [{"phase_identifier": "Copper", "Grain_Number": 150}],
                "simulation": {"Load_Type": "tension"},
            },
        )
        cls.public = JSONData.objects.create(
            owner=cls.other,
            access_type="all",
            data={
                "identifier": "public-copper",
                "title": "Copper compression experiment",
                "phase": [{"phase_identifier": "Copper", "Grain_Number": 1000}],
            },
        )
        cls.shared = JSONData.objects.create(
            owner=cls.other,
            access_type="c",
            data={
                "identifier": "shared-nickel",
                "phase": [{"phase_identifier": "Nickel", "Grain_Number": "175"}],
                "shared_only_field": "visible",
            },
        )
        cls.shared.shared_users.add(cls.viewer)
        cls.hidden = JSONData.objects.create(
            owner=cls.other,
            access_type="c",
            data={
                "identifier": "hidden-copper",
                "phase": [{"phase_identifier": "Copper", "Grain_Number": 150}],
                "private_secret_field": "confidential",
            },
        )

    def setUp(self):
        """
        Authenticate the viewer without using real account credentials
        """
        self.client.force_login(self.viewer)

    def test_range_conditions_search_nested_numbers_not_substrings(self):
        """
        Compare numeric values while keeping private records out of results
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "Grain_Number",
            "condition_operator": "between",
            "condition_value": "100",
            "condition_value_to": "200",
        })
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [obj.pk for obj in response.context["data_objects"]],
            [self.own.pk, self.shared.pk],
        )

    def test_results_put_public_first_and_keep_newest_first_within_each_access_group(self):
        """
        Public matches precede private matches without changing their visibility

        Upload time and object ID retain a stable order within each access group.
        """
        newer_public = JSONData.objects.create(
            owner=self.other, access_type="all",
            data={"identifier": "new-public", "phase": [{"Grain_Number": 150}]},
        )
        newer_private = JSONData.objects.create(
            owner=self.viewer, access_type="c",
            data={"identifier": "new-private", "phase": [{"Grain_Number": 150}]},
        )
        params = {
            "condition_field": "grain_count",
            "condition_operator": "gt",
            "condition_value": "50",
        }
        expected = [newer_public.pk, self.public.pk, newer_private.pk,
                    self.shared.pk, self.own.pk]

        for equal_timestamps in (False, True):
            with self.subTest(equal_timestamps=equal_timestamps):
                if equal_timestamps:
                    JSONData.objects.update(uploaded_at=self.own.uploaded_at)
                response = self.client.get(reverse("search"), params)
                self.assertEqual(
                    [obj.pk for obj in response.context["data_objects"]], expected
                )
                self.assertEqual(response.context.get("result_count"), 5)

    def test_result_count_follows_access_filters_and_matching_conditions(self):
        """
        Count only accessible records that satisfy the complete submitted search

        A private record belonging to another user must not affect any count.
        """
        for access, expected in [
            ("", 3), ("public", 1), ("my_private", 1),
            ("my_data", 1), ("shared_with_me", 1),
        ]:
            with self.subTest(access=access):
                response = self.client.get(reverse("search"), {
                    "access": access,
                    "condition_field": "grain_count",
                    "condition_operator": "gt",
                    "condition_value": "50",
                })
                self.assertEqual(response.context.get("result_count"), expected)
        response = self.client.get(reverse("search"), {
            "phase": "copper",
            "condition_field": "grain_count",
            "condition_operator": "lt",
            "condition_value": "200",
        })
        self.assertEqual(response.context.get("result_count"), 1)
        self.assertEqual([obj.pk for obj in response.context["data_objects"]], [self.own.pk])

    def test_result_count_is_zero_for_empty_unsubmitted_and_invalid_searches(self):
        """
        Empty and invalid searches cannot report accessible records as matches
        """
        for params in [
            {}, {"keyword": "definitely_absent"},
            {"condition_field": "grain_count", "condition_operator": "gt",
             "condition_value": "invalid"},
        ]:
            with self.subTest(params=params):
                response = self.client.get(reverse("search"), params)
                self.assertEqual(response.context.get("result_count"), 0)
                self.assertFalse(response.context["data_objects"])

    def test_rendered_match_options_follow_selected_field_type(self):
        """
        Render applicable comparisons even when JavaScript is unavailable
        """
        for field, operation, value, expected in [
            ("Grain_Number", "eq", "150", ["eq", "gt", "gte", "lt", "lte", "between"]),
            ("Load_Type", "contains", "tension", ["contains", "exact"]),
            ("Material_parameters", "eq", "150",
             ["contains", "exact", "eq", "gt", "gte", "lt", "lte", "between"]),
            ("elastic_parameters", "contains", "C11 170000", ["contains"]),
            ("plastic_parameters", "contains", "reference_shear_rate 0.001", ["contains"]),
            ("RVE_continuity", "is", "true", ["is"]),
        ]:
            with self.subTest(field=field):
                response = self.client.get(reverse("search"), {
                    "condition_field": field,
                    "condition_operator": operation,
                    "condition_value": value,
                })
                html = response.content.decode()
                select = re.search(
                    r'<select[^>]*id="condition-1-operator"[^>]*>(.*?)</select>',
                    html, re.DOTALL,
                ).group(1)
                self.assertEqual(re.findall(r'<option value="([^"]*)"', select), expected)

    def test_incompatible_comparison_is_preserved_for_correction(self):
        """
        Reject crafted requests without silently changing their comparison
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "Grain_Number",
            "condition_operator": "contains",
            "condition_value": "15",
        })
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        self.assertEqual(response.context["condition_rows"][0]["operator"], "contains")
        self.assertContains(response, 'value="contains" selected')

    def test_field_type_metadata_reaches_initial_form(self):
        """
        Let newly selected fields use the same types as server validation
        """
        response = self.client.get(reverse("search"))
        self.assertContains(response, 'value="grain_count" data-field-type="number"')
        self.assertContains(response, 'value="loading_type" data-field-type="text"')
        self.assertContains(response, 'value="RVE_continuity" data-field-type="boolean"')
        self.assertNotContains(response, 'value="elastic_parameters"')
        self.assertNotContains(response, 'value="plastic_parameters"')

    def test_whole_word_filters_hide_match_and_preserve_access_boundaries(self):
        """
        Render the fixed word comparison while matching only accessible objects
        """
        for obj, model in [
            (self.public, "Isotropic Elasticity"),
            (self.own, "Anisotropic Elasticity"),
            (self.hidden, "Isotropic Elasticity"),
        ]:
            obj.data["phase"] = [{"constitutive_model": {"elastic_model_name": model}}]
            obj.save(update_fields=["data"])
        response = self.client.get(reverse("search"), {
            "condition_field": "elastic_model_name",
            "condition_operator": "words",
            "condition_value": "ELASTICITY isotropic",
        })
        self.assertFalse(response.context["search_errors"])
        self.assertEqual([obj.pk for obj in response.context["data_objects"]], [self.public.pk])
        self.assertEqual(response.context["result_count"], 1)
        row = response.context["condition_rows"][0]
        self.assertTrue(row["simple_text"])
        self.assertEqual(row["operator_choices"], [("words", "All words")])
        self.assertContains(response, 'data-condition-match hidden')
        self.assertContains(response, 'value="words" selected')

    def test_saved_text_comparisons_remain_visible_with_their_original_meaning(self):
        """
        Keep a saved comparison editable without offering it to new text searches
        """
        self.public.data["elastic_model_name"] = "Anisotropic Elasticity"
        self.public.save(update_fields=["data"])
        for operation, count in [("contains", 1), ("exact", 0)]:
            with self.subTest(operation=operation):
                response = self.client.get(reverse("search"), {
                    "condition_field": "elastic_model_name",
                    "condition_operator": operation,
                    "condition_value": "isotropic",
                })
                self.assertFalse(response.context["search_errors"])
                self.assertEqual(response.context["result_count"], count)
                row = response.context["condition_rows"][0]
                self.assertFalse(row["simple_text"])
                self.assertEqual(row["operator"], operation)
                self.assertCountEqual(
                    [value for value, label in row["operator_choices"]], ["words", operation]
                )

    def test_initial_word_comparison_remains_optional_and_available_without_javascript(self):
        """
        Offer whole words on the initial form and ignore its untouched blank row
        """
        response = self.client.get(reverse("search"))
        row = response.context["condition_rows"][0]
        self.assertEqual(row["operator"], "words")
        self.assertIn(("words", "All words"), row["operator_choices"])
        response = self.client.get(reverse("search"), {
            "keyword": "copper", "condition_field": "",
            "condition_operator": "words", "condition_value": "", "condition_value_to": "",
        })
        self.assertFalse(response.context["search_errors"])
        self.assertEqual(response.context["result_count"], 2)

    def test_parameter_exact_requests_fail_without_changing_submitted_intent(self):
        """
        Keep unsupported dictionary equality visible for correction without searching
        """
        for field in ("elastic_parameters", "plastic_parameters"):
            with self.subTest(field=field):
                response = self.client.get(reverse("search"), {
                    "condition_field": field,
                    "condition_operator": "exact",
                    "condition_value": "{'C11': 170000, 'C12': 124000, 'C44': 75000}",
                })
                self.assertTrue(response.context["search_errors"])
                self.assertFalse(response.context["data_objects"])
                self.assertEqual(response.context["condition_rows"][0]["operator"], "exact")
                self.assertContains(response, 'value="exact" selected')
                self.assertContains(response, "Choose Contains words")

    def test_preset_choices_are_grouped_with_defaults_and_temperature_units(self):
        """
        Expose the scientific groups and comparison defaults in the rendered form
        """
        response = self.client.get(reverse("search"))
        elements = list(_html_elements(parse_html(response.content.decode())))
        field = next(element for element in elements if
                     ("id", "condition-1-field") in element.attributes)
        groups = [element for element in _html_elements(field) if element.name == "optgroup"]
        self.assertEqual([dict(group.attributes)["label"] for group in groups], [
            "Microstructure", "Discretization and boundaries", "Material models", "Loading and temperature",
        ])
        fields = {option["value"]: option for option in response.context["field_options"]}
        cases = (
            ("texture_type", "Microstructure", "words", ""),
            ("grain_count", "Microstructure", "eq", ""),
            ("lattice_structure", "Microstructure", "words", ""),
            ("orientation_identifier", "Microstructure", "words", ""),
            ("discretization_type", "Discretization and boundaries", "words", ""),
            ("discretization_count", "Discretization and boundaries", "eq", ""),
            ("RVE_continuity", "Discretization and boundaries", "is", ""),
            ("elastic_model_name", "Material models", "words", ""),
            ("plastic_model_name", "Material models", "words", ""),
            ("loading_type", "Loading and temperature", "words", ""),
            ("loading_mode", "Loading and temperature", "words", ""),
            ("global_temperature", "Loading and temperature", "eq", "K"),
        )
        for value, group, default, unit in cases:
            with self.subTest(field=value):
                self.assertEqual(fields[value]["group"], group)
                self.assertEqual(fields[value]["default_operator"], default)
                self.assertEqual(fields[value]["unit"], unit)
        self.assertEqual(fields["lattice_structure"]["label"], "Crystal structure")

    def test_boolean_value_renders_as_select_and_preserves_false_or_invalid_input(self):
        """
        Keep continuity usable without JavaScript and preserve rejected URL values
        """
        for value, invalid in (("true", False), ("false", False), ("yes", True)):
            with self.subTest(value=value):
                response = self.client.get(reverse("search"), {
                    "condition_field": "RVE_continuity",
                    "condition_operator": "is",
                    "condition_value": value,
                })
                row = response.context["condition_rows"][0]
                self.assertIn("boolean_value", row)
                self.assertTrue(row["boolean_value"])
                self.assertEqual(bool(response.context["search_errors"]), invalid)
                elements = list(_html_elements(parse_html(response.content.decode())))
                control = next(element for element in elements if
                               ("id", "condition-1-value") in element.attributes)
                self.assertEqual(control.name, "select")
                options = [dict(element.attributes) for element in _html_elements(control)
                           if element.name == "option"]
                self.assertTrue({"true", "false"}.issubset({option["value"] for option in options}))
                self.assertEqual([option["value"] for option in options if "selected" in option], [value])
                self.assertEqual(row["value"], value)
                if invalid:
                    self.assertFalse(response.context["data_objects"])

    def test_valid_boolean_values_with_spaces_restore_the_supported_choice(self):
        """
        Render the same boolean choice that the parser accepts after trimming
        """
        for submitted, expected in ((" true ", "true"), ("\tfalse\n", "false")):
            with self.subTest(value=submitted):
                response = self.client.get(reverse("search"), {
                    "condition_field": "RVE_continuity",
                    "condition_operator": "is",
                    "condition_value": submitted,
                })
                self.assertFalse(response.context["search_errors"])
                self.assertEqual(response.context["condition_rows"][0]["value"], expected)
                self.assertContains(response, f'value="{expected}" selected')
                self.assertNotContains(response, "(unsupported)")

    def test_temperature_rows_display_kelvin_and_preserve_invalid_bounds(self):
        """
        Label both temperature bounds in Kelvin while retaining rejected input
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "global_temperature",
            "condition_operator": "between",
            "condition_value": "-1",
            "condition_value_to": "300",
        })
        row = response.context["condition_rows"][0]
        self.assertIn("unit", row)
        self.assertEqual(row["unit"], "K")
        self.assertEqual(row["value"], "-1")
        self.assertEqual(row["value_to"], "300")
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        self.assertContains(response, "(K)")

    def test_removed_parameter_choices_return_only_when_used_by_a_saved_url(self):
        """
        Keep old parameter conditions editable in the saved filter group
        """
        response = self.client.get(reverse("search"), {
            "condition_field": ["elastic_parameters", "plastic_parameters"],
            "condition_operator": ["contains", "contains"],
            "condition_value": ["C11 170000", "reference_shear_rate 0.001"],
        })
        self.assertFalse(response.context["search_errors"])
        fields = {option["value"]: option for option in response.context["field_options"]}
        for field in ("elastic_parameters", "plastic_parameters"):
            self.assertEqual(fields[field]["group"], "Saved filters")
            self.assertEqual(fields[field]["type"], "parameters")
            self.assertEqual(fields[field]["default_operator"], "contains")
        self.assertContains(response, '<optgroup label="Saved filters">')

    def test_only_active_legacy_tokens_are_restored_with_their_original_types(self):
        """
        Keep bookmarked comparisons editable without offering obsolete new choices
        """
        response = self.client.get(reverse("search"), {
            "condition_field": ["Grain_Number", "Material_parameters"],
            "condition_operator": ["eq", "eq"],
            "condition_value": ["150", "170000"],
        })
        self.assertFalse(response.context["search_errors"])
        self.assertContains(response, 'value="Grain_Number" data-field-type="number"')
        self.assertContains(response, 'value="Material_parameters" data-field-type="array"')
        fields = {option["value"]: option for option in response.context["field_options"]}
        self.assertIn("legacy", fields["Grain_Number"]["label"].casefold())
        self.assertNotIn("Stress_Type", fields)
        self.assertNotIn("Load_Descriptor", fields)

    def test_empty_match_stays_unselected_until_user_corrects_it(self):
        """
        Avoid displaying a default comparison for a rejected empty selection
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "Grain_Number",
            "condition_operator": "",
            "condition_value": "150",
        })
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        select = re.search(
            r'<select[^>]*id="condition-1-operator"[^>]*>(.*?)</select>',
            response.content.decode(), re.DOTALL,
        ).group(1)
        self.assertIn('<option value="" selected>', select)

    def test_common_filters_omit_redundant_keywords_input(self):
        """
        Avoid repeating common metadata in the fixed parameter menu
        """
        response = self.client.get(reverse("search"))
        self.assertNotContains(response, '<input type="text" name="keywords"')
        for field in ("identifier", "creator", "software", "phase", "owner", "access", "title"):
            self.assertContains(response, f'name="{field}"')
        field_values = [option["value"] for option in response.context["field_options"]]
        for field in (
            "identifier", "creator", "software", "phase", "owner", "access",
            "title", "keywords", "Abaqus-Version", "software_version",
        ):
            self.assertNotIn(field, field_values)
            self.assertNotIn(json.dumps([field]), field_values)

    def test_common_filters_prioritize_identifier_access_and_owner(self):
        """
        Keep visual and keyboard order focused on identity and access
        """
        response = self.client.get(reverse("search"))
        elements = _html_elements(parse_html(response.content.decode()))
        common = next(element for element in elements if
                      ("aria-labelledby", "commonFiltersTitle") in element.attributes)
        fields = [dict(element.attributes) for element in _html_elements(common)
                  if element.name in ("input", "select")]
        self.assertEqual(fields[0]["id"], "id_identifier")
        self.assertEqual(
            [field["name"] for field in fields],
            ["identifier", "access", "owner", "creator", "software", "phase", "title"],
        )

    def test_owner_label_keeps_the_uploader_filter_binding(self):
        """
        Describe the uploader while preserving owner links and submitted values
        """
        response = self.client.get(reverse("search"), {"owner": "search_viewer"})
        elements = list(_html_elements(parse_html(response.content.decode())))
        label = next(element for element in elements if element.name == "label"
                     and ("for", "id_owner") in element.attributes)
        self.assertEqual(label.children, ["Owner (uploaded by)"])
        owner = next(element for element in elements if
                     ("id", "id_owner") in element.attributes)
        self.assertEqual(dict(owner.attributes)["name"], "owner")
        self.assertEqual(dict(owner.attributes)["value"], "search_viewer")

    def test_bottom_search_shares_the_complete_keyword_form(self):
        """
        Keep both search buttons in one GET form containing every filter group
        """
        response = self.client.get(reverse("search"))
        elements = list(_html_elements(parse_html(response.content.decode())))
        forms = [element for element in elements if
                 ("id", "advancedSearchForm") in element.attributes]
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form.name, "form")
        self.assertEqual(dict(form.attributes)["method"].lower(), "get")
        form_elements = list(_html_elements(form))
        self.assertEqual(sum(element.name == "form" for element in form_elements), 1)
        panel = next(element for element in form_elements if
                     ("id", "advancedSearchPanel") in element.attributes)
        actions = [element for element in panel.children if not isinstance(element, str)
                   and "advanced-search-actions" in dict(element.attributes).get("class", "").split()]
        self.assertEqual(len(actions), 1, "Bottom actions must be inside the advanced panel")
        groups = [element for element in panel.children if not isinstance(element, str)
                  and element.name == "section"]
        self.assertEqual(len(groups), 2)
        for group in groups:
            self.assertLess(panel.children.index(group), panel.children.index(actions[0]))
        submits = [element for element in form_elements if element.name == "button"
                   and ("type", "submit") in element.attributes]
        self.assertEqual(len(submits), 2)
        self.assertTrue(any(element is submits[1] for element in _html_elements(actions[0])))
        self.assertFalse(any(element is submits[0] for element in _html_elements(panel)))
        for button in submits:
            self.assertIn("Search", button.children)
            self.assertFalse({"form", "formaction", "formmethod"} & dict(button.attributes).keys())
        fields = [dict(element.attributes) for element in form_elements
                  if element.name in ("input", "select")]
        self.assertCountEqual(
            [field["name"] for field in fields],
            ["keyword", "title", "identifier", "creator", "software", "phase", "owner", "access",
             "condition_field", "condition_operator", "condition_value", "condition_value_to"],
        )
        for field in fields:
            self.assertNotIn("form", field)
            self.assertNotIn("disabled", field)

    def test_both_clear_links_discard_every_filter(self):
        """
        Clear the complete search from either the top or bottom control
        """
        response = self.client.get(reverse("search"), {
            "keyword": "copper", "title": "experiment", "owner": "search_viewer",
            "identifier": "own", "creator": "Ronak", "software": "Abaqus",
            "phase": "Copper", "access": "my_data", "keywords": "crystal",
            "condition_field": "Grain_Number", "condition_operator": "between",
            "condition_value": "100", "condition_value_to": "200",
        })
        elements = _html_elements(parse_html(response.content.decode()))
        form = next(element for element in elements if
                    ("id", "advancedSearchForm") in element.attributes)
        links = [element for element in _html_elements(form)
                 if element.name == "a" and "Clear" in element.children]
        self.assertEqual(len(links), 2)
        for link in links:
            with self.subTest(link=str(link)):
                self.assertEqual(dict(link.attributes)["href"], reverse("search"))
                cleared = self.client.get(dict(link.attributes)["href"])
                self.assertFalse(cleared.wsgi_request.GET)
                self.assertFalse(cleared.context["search_performed"])
                self.assertFalse(cleared.context["advanced_open"])
                self.assertNotContains(cleared, 'id="id_legacy_keywords"')

    def test_legacy_keyword_filter_stays_visible_and_editable(self):
        """
        Prevent old bookmarked keyword filters from silently restricting results
        """
        response = self.client.get(reverse("search"), {"keywords": "crystal"})
        self.assertContains(response, 'id="id_legacy_keywords"')
        self.assertContains(response, 'name="keywords"')
        self.assertContains(response, 'value="crystal"')
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.own.pk]
        )

    def test_basic_common_and_field_conditions_all_apply(self):
        """
        Require all kinds of conditions to match the same accessible record
        """
        response = self.client.get(reverse("search"), {
            "keyword": "copper experiment",
            "creator": "ICAMS Ronak",
            "condition_field": ["Grain_Number", "Load_Type"],
            "condition_operator": ["gt", "exact"],
            "condition_value": ["100", "TENSION"],
            "condition_value_to": ["", ""],
        })
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.own.pk]
        )

    def test_common_fields_match_all_words_in_any_order(self):
        """
        Apply the familiar basic search word behavior to common fields
        """
        for field, query in [
            ("title", "EXPERIMENT copper"),
            ("creator", "ICAMS shoghi"),
            ("software", "CAE abaqus"),
            ("keywords", "plasticity crystal"),
        ]:
            with self.subTest(field=field):
                response = self.client.get(reverse("search"), {field: query})
                ids = [obj.pk for obj in response.context["data_objects"]]
                self.assertIn(self.own.pk, ids)
                response = self.client.get(reverse("search"), {
                    field: query + " definitely_absent",
                })
                self.assertFalse(response.context["data_objects"])

    def test_field_choices_do_not_disclose_custom_json_fields(self):
        """
        Exclude private field names even before a search is submitted
        """
        response = self.client.get(reverse("search"))
        fields = [option["value"] for option in response.context["field_options"]]
        self.assertIn("grain_count", fields)
        self.assertNotIn("shared_only_field", fields)
        self.assertNotIn("private_secret_field", fields)
        self.assertNotContains(response, "private_secret_field")
        self.assertFalse(response.context["search_performed"])

    def test_revoked_share_disappears_from_results(self):
        """
        Keep the fixed catalog while rechecking result permissions
        """
        self.shared.shared_users.remove(self.viewer)
        response = self.client.get(reverse("search"), {
            "condition_field": "Grain_Number",
            "condition_operator": "eq",
            "condition_value": "175",
            "condition_value_to": "",
        })
        self.assertFalse(response.context["data_objects"])
        self.assertFalse(response.context["search_errors"])
        self.assertIn(
            "Grain_Number",
            [option["value"] for option in response.context["field_options"]],
        )

    def test_invalid_numeric_input_preserves_form_and_returns_no_results(self):
        """
        Reject invalid conditions instead of silently running a broader search
        """
        response = self.client.get(reverse("search"), {
            "keyword": "copper",
            "condition_field": '["phase","Grain_Number"]',
            "condition_operator": "gt",
            "condition_value": "abc",
            "condition_value_to": "",
        })
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        self.assertTrue(response.context["advanced_open"])
        self.assertEqual(response.context["condition_rows"][0]["value"], "abc")
        self.assertContains(response, "abc")

    def test_too_many_conditions_cannot_broaden_search(self):
        """
        Reject excessive input without discarding conditions silently
        """
        response = self.client.get(reverse("search"), {
            "condition_field": ['["identifier"]'] * 11,
            "condition_operator": ["contains"] * 11,
            "condition_value": ["copper"] * 11,
            "condition_value_to": [""] * 11,
        })
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])

    def test_untouched_condition_does_not_trigger_search(self):
        """
        Ignore the empty optional condition row
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "",
            "condition_operator": "contains",
            "condition_value": "",
            "condition_value_to": "",
        })
        self.assertFalse(response.context["search_performed"])
        self.assertFalse(response.context["search_errors"])

    def test_new_access_filters_keep_existing_ownership_rules(self):
        """
        Distinguish owned records from private records explicitly shared to us
        """
        for access, expected in [
            ("my_data", [self.own.pk]),
            ("shared_with_me", [self.shared.pk]),
            ("public", [self.public.pk]),
            ("my_private", [self.own.pk]),
        ]:
            with self.subTest(access=access):
                response = self.client.get(reverse("search"), {"access": access})
                self.assertCountEqual(
                    [obj.pk for obj in response.context["data_objects"]], expected
                )

    def test_anonymous_search_requires_login(self):
        """
        Keep data search and field suggestions behind authentication
        """
        self.client.logout()
        response = self.client.get(reverse("search"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_basic_search_still_matches_words_across_accessible_metadata(self):
        """
        Preserve the ordinary keyword search while adding field conditions
        """
        response = self.client.get(reverse("search"), {"keyword": "CAE copper ICAMS"})
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.own.pk]
        )

    def test_field_labels_and_invalid_values_are_html_escaped(self):
        """
        Treat field names and query values as data rather than executable markup
        """
        payload = '<img src=x onerror="alert(1)">'
        self.own.data[payload] = "example"
        self.own.save(update_fields=["data"])
        response = self.client.get(reverse("search"), {
            "condition_field": json.dumps([payload]),
            "condition_operator": "gt",
            "condition_value": payload,
            "condition_value_to": "",
        })
        self.assertNotContains(response, payload)
        self.assertContains(response, "&lt;img")
        self.assertFalse(response.context["data_objects"])

    def test_multiple_share_recipients_do_not_duplicate_a_result(self):
        """
        Return one card per data object even when joins find several recipients
        """
        self.own.shared_users.add(self.viewer, self.other)
        response = self.client.get(reverse("search"), {"access": "my_data"})
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.own.pk]
        )
        self.assertEqual(response.context.get("result_count"), 1)

    def test_submitted_path_with_extra_spaces_is_restored_as_selected(self):
        """
        Normalize valid paths so revisiting the URL preserves the field selection
        """
        response = self.client.get(reverse("search"), {
            "condition_field": '[ "phase", "Grain_Number" ]',
            "condition_operator": "eq",
            "condition_value": "150",
            "condition_value_to": "",
        })
        row = response.context["condition_rows"][0]
        self.assertEqual(row["field"], '["phase","Grain_Number"]')
        self.assertFalse(row["field_available"])
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.own.pk]
        )

    def test_overly_nested_invalid_path_returns_a_form_error(self):
        """
        Render rejected paths safely instead of parsing them without a bound
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "[" * 1100 + '"value"' + "]" * 1100,
            "condition_operator": "contains",
            "condition_value": "anything",
            "condition_value_to": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])

    def test_invalid_unicode_path_can_be_displayed_for_correction(self):
        """
        Avoid decoding rejected surrogate escapes into invalid HTML text
        """
        response = self.client.get(reverse("search"), {
            "condition_field": '["\\ud800"]',
            "condition_operator": "contains",
            "condition_value": "anything",
            "condition_value_to": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])

    def test_fixed_fields_are_available_without_accessible_records(self):
        """
        Offer the example schema's parameter choices before any upload
        """
        newcomer = User.objects.create_user(username="new_search_viewer")
        self.client.force_login(newcomer)
        self.public.access_type = "c"
        self.public.save(update_fields=["access_type"])
        response = self.client.get(reverse("search"))
        self.assertEqual(
            [option["value"] for option in response.context["field_options"]],
            [
                "texture_type", "grain_count", "lattice_structure", "orientation_identifier",
                "discretization_type", "discretization_count", "RVE_continuity",
                "elastic_model_name", "plastic_model_name", "loading_type", "loading_mode",
                "global_temperature",
            ],
        )
        self.assertFalse(response.context["search_performed"])

    def test_missing_fixed_field_returns_no_matches_not_a_form_error(self):
        """
        Allow selecting a supported parameter absent from the current records
        """
        response = self.client.get(reverse("search"), {
            "condition_field": "texture_type",
            "condition_operator": "contains",
            "condition_value": "random",
            "condition_value_to": "",
        })
        self.assertFalse(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        self.assertTrue(response.context["condition_rows"][0]["field_available"])

    def test_legacy_path_search_does_not_broaden_to_other_locations(self):
        """
        Preserve exact paths in bookmarked searches after changing the dropdown
        """
        self.own.data["other"] = {"Grain_Number": 400}
        self.own.save(update_fields=["data"])
        params = {
            "condition_field": '["phase","Grain_Number"]',
            "condition_operator": "eq",
            "condition_value": "400",
            "condition_value_to": "",
        }
        response = self.client.get(reverse("search"), params)
        self.assertFalse(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        params["condition_field"] = "Grain_Number"
        response = self.client.get(reverse("search"), params)
        self.assertFalse(response.context["search_errors"])
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.own.pk]
        )

    def test_example_presets_keep_and_logic_and_access_boundaries(self):
        """
        Search real nested parameters only within the same accessible object
        """
        example_path = Path(__file__).with_name("fixtures") / "search_fields.json"
        example = json.loads(example_path.read_text(encoding="utf-8"))
        for obj in (self.own, self.public, self.shared, self.hidden):
            obj.data = dict(example, identifier=obj.data["identifier"])
            obj.save(update_fields=["data"])
        params = {
            "condition_field": ["grain_count", "texture_type", "elastic_model_name", "loading_type"],
            "condition_operator": ["eq", "exact", "contains", "exact"],
            "condition_value": ["343", "GOSS", "anisotropic elasticity", "force"],
        }
        response = self.client.get(reverse("search"), params)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["search_errors"])
        self.assertCountEqual(
            [obj.pk for obj in response.context["data_objects"]],
            [self.own.pk, self.public.pk, self.shared.pk],
        )
        params["condition_value"][-1] = "displacement"
        response = self.client.get(reverse("search"), params)
        self.assertFalse(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
        params["condition_operator"][0] = "contains"
        response = self.client.get(reverse("search"), params)
        self.assertTrue(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])

    def test_recursive_boolean_and_kelvin_conditions_keep_search_and_feed_permissions(self):
        """
        Match recursive fields on accessible records without exposing private activity
        """
        for obj in (self.own, self.public, self.shared, self.hidden):
            obj.data = {
                "identifier": obj.data["identifier"],
                "title": "Copper simulation",
                "simulation": [{"Grain Number": "343", "RVE-Continuity": True,
                                "global temperature": 25, "units": {"Temperature": "C"}}],
            }
            obj.save(update_fields=["data"])
        params = {
            "keyword": "copper", "title": "simulation",
            "condition_field": ["grain_count", "RVE_continuity", "global_temperature"],
            "condition_operator": ["gte", "is", "eq"],
            "condition_value": ["300", "true", "298.15"],
        }
        response = self.client.get(reverse("search"), params)
        self.assertFalse(response.context["search_errors"])
        self.assertCountEqual([obj.pk for obj in response.context["data_objects"]],
                              [self.own.pk, self.public.pk, self.shared.pk])
        feed = self.client.get(reverse("search_live_data_objects"))
        self.assertEqual([obj["id"] for obj in feed.json()["objects"]], [self.public.pk])
        self.shared.shared_users.remove(self.viewer)
        response = self.client.get(reverse("search"), params)
        self.assertCountEqual([obj.pk for obj in response.context["data_objects"]],
                              [self.own.pk, self.public.pk])
        params["condition_value"][1] = "false"
        response = self.client.get(reverse("search"), params)
        self.assertFalse(response.context["search_errors"])
        self.assertFalse(response.context["data_objects"])
