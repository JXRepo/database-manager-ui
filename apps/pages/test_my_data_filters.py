from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class MyDataFilterTests(TestCase):
    """
    Check dropdown filtering and ownership on the My Data page
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create varied owned records and accessible records from another user
        """
        cls.owner = User.objects.create_user(username="filter_owner")
        cls.other = User.objects.create_user(username="filter_other")
        cls.public = JSONData.objects.create(
            owner=cls.owner, access_type="all",
            data={
                "identifier": "public-copper", "software": "DAMASK",
                "creator": ["Alice", "ALICE", "Bob"],
                "phase": [{"phase_identifier": "Copper"},
                          {"phase_name": "Nickel", "phase_identifier": "2"}],
            },
        )
        cls.private = JSONData.objects.create(
            owner=cls.owner, access_type="c",
            data={
                "identifier": "private-copper", "software": {"name": "Abaqus"},
                "creator": {"creator_name": "Alice"},
                "phase": {"phase_identifier": "Copper"},
            },
        )
        cls.private.shared_users.add(cls.other)
        cls.steel = JSONData.objects.create(
            owner=cls.owner, access_type="c",
            data={
                "identifier": "private-steel", "software": " DAMASK ",
                "creator": "Carol", "phase": "Steel",
            },
        )
        for access in ("all", "c"):
            obj = JSONData.objects.create(
                owner=cls.other, access_type=access,
                data={
                    "identifier": f"foreign-{access}", "software": "Foreign Solver",
                    "creator": "Foreign Creator", "phase": "Silver",
                },
            )
            obj.shared_users.add(cls.owner)

    def setUp(self):
        """
        Sign in as the uploader before each request
        """
        self.client.force_login(self.owner)

    def test_each_dropdown_filters_owned_objects(self):
        """
        Match exact metadata values and include shared owned data as private
        """
        cases = [
            ({"access": "public"}, [self.public.pk]),
            ({"access": "private"}, [self.steel.pk, self.private.pk]),
            ({"software": "damask"}, [self.steel.pk, self.public.pk]),
            ({"software": "Abaqus"}, [self.private.pk]),
            ({"phase": "Copper"}, [self.private.pk, self.public.pk]),
            ({"phase": "Nickel"}, [self.public.pk]),
            ({"creator": "Alice"}, [self.private.pk, self.public.pk]),
            ({"creator": "Bob"}, [self.public.pk]),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                response = self.client.get(reverse("json_data_list"), query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [obj.pk for obj in response.context["data_objects"]], expected,
                )

    def test_filters_combine_on_the_same_record(self):
        """
        Require every selected dropdown value on one owned object
        """
        response = self.client.get(reverse("json_data_list"), {
            "access": "private", "software": "abaqus",
            "phase": "copper", "creator": "alice",
        })
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.private.pk],
        )
        self.assertEqual(response.context["result_count"], 1)
        self.assertEqual(response.context["total_count"], 3)

    def test_phase_name_takes_precedence_over_a_phase_identifier(self):
        """
        Offer the material name when a phase also has a local identifier
        """
        self.steel.data["phase"] = {"name": "Iron", "phase_identifier": "7"}
        self.steel.save(update_fields=["data"])
        response = self.client.get(reverse("json_data_list"), {"phase": "Iron"})
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]], [self.steel.pk],
        )

    def test_choices_exclude_other_users_and_count_objects_once(self):
        """
        Build counts from owned objects without duplicate names or foreign data
        """
        response = self.client.get(reverse("json_data_list"))
        choices = {}
        for field in response.context["my_data_filters"]:
            choices[field["name"]] = {
                option["value"]: option["count"] for option in field["options"]
            }
        self.assertEqual(choices, {
            "access": {"public": 1, "private": 2},
            "software": {"abaqus": 1, "damask": 2},
            "phase": {"copper": 2, "nickel": 1, "steel": 1},
            "creator": {"alice": 2, "bob": 1, "carol": 1},
        })
        self.assertNotContains(response, "Foreign Solver")
        self.assertNotContains(response, "Foreign Creator")
        self.assertNotContains(response, "Silver")

    def test_option_counts_respect_other_selected_filters(self):
        """
        Show the number available after applying the other dropdown conditions
        """
        response = self.client.get(reverse("json_data_list"), {"access": "private"})
        software = next(
            field for field in response.context["my_data_filters"]
            if field["name"] == "software"
        )
        self.assertEqual(software["total"], 2)
        self.assertEqual(
            {option["value"]: option["count"] for option in software["options"]},
            {"abaqus": 1, "damask": 1},
        )

    def test_unknown_values_do_not_broaden_results(self):
        """
        Retain unavailable bookmarked values while returning an empty list
        """
        for field, value in (("software", "DAM"), ("phase", "missing"),
                             ("creator", "ali"), ("access", "other")):
            with self.subTest(field=field):
                response = self.client.get(reverse("json_data_list"), {field: value})
                self.assertEqual(list(response.context["data_objects"]), [])
                selected = next(
                    item for item in response.context["my_data_filters"]
                    if item["name"] == field
                )
                self.assertEqual(selected["value"], value.casefold())
                self.assertContains(response, "No data objects match these filters")
                self.assertContains(response, 'id="myDataFilterForm"')

    def test_clear_restores_all_owned_objects_in_newest_order(self):
        """
        Keep default ordering and make the clear link remove every condition
        """
        response = self.client.get(reverse("json_data_list"), {"software": "abaqus"})
        self.assertContains(response, f'href="{reverse("json_data_list")}"')
        response = self.client.get(reverse("json_data_list"))
        self.assertEqual(
            [obj.pk for obj in response.context["data_objects"]],
            [self.steel.pk, self.private.pk, self.public.pk],
        )

    def test_metadata_labels_and_selected_queries_are_escaped(self):
        """
        Render uploaded names and stale query values as text rather than markup
        """
        JSONData.objects.create(owner=self.owner, data={
            "software": '<img src=x onerror="alert(1)">', "phase": "Copper",
        })
        response = self.client.get(reverse("json_data_list"), {
            "creator": '<script>alert("query")</script>',
        })
        self.assertContains(response, "&lt;img")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<img src=x')
        self.assertNotContains(response, '<script>alert("query")')

    def test_missing_or_unrecognized_metadata_remains_in_all(self):
        """
        Avoid inventing names from parameter dictionaries or nontext values
        """
        obj = JSONData.objects.create(owner=self.owner, data={
            "software": None, "creator": [False, 123, {"affiliation": "Lab"}],
            "phase": [{"elastic_model": "Not a phase name"}],
        })
        response = self.client.get(reverse("json_data_list"))
        self.assertEqual(response.context["total_count"], 4)
        self.assertIn(obj.pk, [item.pk for item in response.context["data_objects"]])
        self.assertNotContains(response, '>Not a phase name (')
        self.assertNotContains(response, '>Lab (')

    def test_empty_account_still_has_filters(self):
        """
        Keep a usable empty state and zero result count before the first upload
        """
        self.client.force_login(User.objects.create_user(username="empty_filter_owner"))
        response = self.client.get(reverse("json_data_list"))
        self.assertEqual(response.context["total_count"], 0)
        self.assertContains(response, "No uploaded data found")
        self.assertContains(response, 'id="myDataFilterForm"')
        self.assertNotContains(response, 'id="myDataBulkActionForm"')

    def test_filtering_requires_sign_in(self):
        """
        Do not expose uploaded metadata to anonymous visitors
        """
        self.client.logout()
        response = self.client.get(reverse("json_data_list"), {"phase": "Copper"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))
