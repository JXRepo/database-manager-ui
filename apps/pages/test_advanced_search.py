import json

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
            "condition_field": '["phase","Grain_Number"]',
            "condition_operator": "between",
            "condition_value": "100",
            "condition_value_to": "200",
        })
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [obj.pk for obj in response.context["data_objects"]],
            [self.own.pk, self.shared.pk],
        )

    def test_common_filters_omit_redundant_keywords_input(self):
        """
        Keep keywords available as a data field without a permanent extra input
        """
        response = self.client.get(reverse("search"))
        self.assertNotContains(response, '<input type="text" name="keywords"')
        for field in ("identifier", "creator", "software", "phase", "owner", "access", "title"):
            self.assertContains(response, f'name="{field}"')
        self.assertIn(
            '["keywords"]',
            [option["value"] for option in response.context["field_options"]],
        )

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

    def test_basic_common_and_dynamic_conditions_all_apply(self):
        """
        Require all kinds of conditions to match the same accessible record
        """
        response = self.client.get(reverse("search"), {
            "keyword": "copper experiment",
            "creator": "ICAMS Ronak",
            "condition_field": ['["phase","Grain_Number"]', '["software"]'],
            "condition_operator": ["gt", "exact"],
            "condition_value": ["100", "ABAQUS CAE"],
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

    def test_field_choices_include_only_accessible_data(self):
        """
        Exclude private field names even before a search is submitted
        """
        response = self.client.get(reverse("search"))
        paths = [json.loads(option["value"]) for option in response.context["field_options"]]
        self.assertIn(["phase", "Grain_Number"], paths)
        self.assertIn(["shared_only_field"], paths)
        self.assertNotIn(["private_secret_field"], paths)
        self.assertNotContains(response, "private_secret_field")
        self.assertFalse(response.context["search_performed"])

    def test_revoked_share_disappears_from_choices_and_results(self):
        """
        Recheck permissions instead of caching another user's field names
        """
        self.shared.shared_users.remove(self.viewer)
        response = self.client.get(reverse("search"), {
            "condition_field": '["shared_only_field"]',
            "condition_operator": "contains",
            "condition_value": "visible",
            "condition_value_to": "",
        })
        self.assertFalse(response.context["data_objects"])
        self.assertNotIn(
            '["shared_only_field"]',
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
        self.assertTrue(row["field_available"])
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
