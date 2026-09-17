import json
import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


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
        self.assertContains(response, 'value="elastic_parameters" data-field-type="parameters"')
        self.assertContains(response, 'value="plastic_parameters" data-field-type="parameters"')

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
                "orientation_identifier", "texture_type", "grain_count",
                "discretization_count", "elastic_model_name", "elastic_parameters",
                "plastic_model_name", "plastic_parameters", "loading_type",
                "loading_mode", "global_temperature",
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
        example_path = Path(__file__).resolve().parents[2] / "example_json_files" / "a46fde6c1_public.json"
        example = json.loads(example_path.read_text(encoding="utf-8"))
        for obj in (self.own, self.public, self.shared, self.hidden):
            obj.data = dict(example, identifier=obj.data["identifier"])
            obj.save(update_fields=["data"])
        params = {
            "creator": "XUE JUN",
            "condition_field": ["grain_count", "texture_type", "elastic_parameters", "loading_type"],
            "condition_operator": ["eq", "exact", "contains", "exact"],
            "condition_value": ["343", "GOSS", "C11 170000", "force"],
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
