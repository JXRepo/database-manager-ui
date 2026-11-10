import csv
import io
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class SchemaPlotTests(TestCase):
    """
    Display supplied equivalent curves using the current MiMeDat field names
    """

    def test_detail_uses_supplied_equivalent_arrays_without_recalculating_them(self):
        """
        Keep supplied curves authoritative even when tensor components also exist
        """
        owner = User.objects.create_user(username="schema-plot-owner")
        self.client.force_login(owner)
        groups = (
            ("stress", "stress", "equivalent_stress", [0, 1, 8, 4, 0], "stress", "MPa"),
            ("total_strain", "strain", "equivalent_strain", [0, 4e-6, 0.2, 0.1, 0], "strain", ""),
            ("plastic_strain", "plastic_strain", "equivalent_plastic_strain", [0, 4e-38, 0.1, 0.05, 0], "plastic_strain", ""),
        )
        for with_components in (False, True):
            with self.subTest(with_components=with_components):
                data = {"units": {"Stress": "MPa", "Strain": 1}}
                for group, prefix, key, values, _kind, _unit in groups:
                    data[group] = {key: values}
                    if with_components:
                        for component in ("11", "22", "33", "12", "13", "23"):
                            data[group][f"{prefix}_{component}"] = [0] * len(values)
                obj = JSONData.objects.create(owner=owner, data=data)

                response = self.client.get(reverse("json_data_detail", args=[obj.pk]))

                self.assertEqual(response.status_code, 200)
                variables = response.context["plot_variables"]
                by_key = {variable["key"]: variable for variable in variables}
                self.assertEqual(len(variables), len(by_key))
                self.assertNotIn("total_strain.equivalent_total_strain", by_key)
                for group, _prefix, key, values, kind, unit in groups:
                    variable = by_key[f"{group}.{key}"]
                    self.assertEqual(variable["values"], values)
                    self.assertEqual(variable["short_label"], key)
                    self.assertEqual(variable["kind"], kind)
                    self.assertEqual(variable["unit"], unit)
                    self.assertEqual(variable["component"], "equivalent")
                obj.refresh_from_db()
                self.assertEqual(json.dumps(obj.data), json.dumps(data))
                exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
                self.assertEqual(exported.json(), data)

    def test_supplied_empty_equivalent_array_is_not_replaced_with_calculated_values(self):
        """
        Leave a supplied empty curve empty instead of inventing a replacement
        """
        owner = User.objects.create_user(username="empty-schema-plot-owner")
        self.client.force_login(owner)
        data = {"total_strain": {"equivalent_strain": []}}
        for component in ("11", "22", "33", "12", "13", "23"):
            data["total_strain"][f"strain_{component}"] = [0, 1]
        obj = JSONData.objects.create(owner=owner, data=data)

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))

        self.assertEqual(response.status_code, 200)
        keys = [variable["key"] for variable in response.context["plot_variables"]]
        self.assertNotIn("total_strain.equivalent_strain", keys)
        self.assertNotIn("total_strain.equivalent_total_strain", keys)

    def test_detail_and_csv_keep_initial_samples_and_distinct_strain_groups(self):
        """
        Preserve zeros, small initial values, and reversals through curve exports

        Formatted field names and scalar wrappers must not merge total strain
        with plastic strain or remove their early samples.
        """
        owner = User.objects.create_user(username="initial-curve-owner")
        self.client.force_login(owner)
        data = {
            "Units": {"Stress": "MPa", "Strain": 1},
            "Stress": [{"Stress 11": [[0], ["0.5"], ["0.5"], ["-0.25"], [0]]}],
            "Total Strain": [{"Strain 11": [[0], ["4.35e-6"], ["0.15"], ["0.04"], [0]]}],
            "Plastic Strain": [{"Plastic Strain 11": [[0], ["4.1e-38"], ["0.14"], ["0.03"], [0]]}],
        }
        expected = {
            "stress.stress_11": [0, 0.5, 0.5, -0.25, 0],
            "total_strain.strain_11": [0, 4.35e-6, 0.15, 0.04, 0],
            "plastic_strain.plastic_strain_11": [0, 4.1e-38, 0.14, 0.03, 0],
        }
        obj = JSONData.objects.create(owner=owner, data=data)

        detail = self.client.get(reverse("json_data_detail", args=[obj.pk]))

        self.assertEqual(detail.status_code, 200)
        variables = {variable["key"]: variable for variable in detail.context["plot_variables"]}
        self.assertEqual(set(variables), set(expected))
        for key, values in expected.items():
            self.assertEqual(variables[key]["values"], values)
        self.assertEqual(variables["total_strain.strain_11"]["kind"], "strain")
        self.assertEqual(variables["plastic_strain.plastic_strain_11"]["kind"], "plastic_strain")

        response = self.client.get(reverse("mechanical_csv_export", args=[obj.pk]))
        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content)
        response.close()
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        self.assertEqual([row[0] for row in rows[1:]], ["0", "1", "2", "3", "4"])
        for key, values in expected.items():
            header = key + (" [MPa]" if key.startswith("stress.") else "")
            column = rows[0].index(header)
            self.assertEqual([float(row[column]) for row in rows[1:]], values)
        obj.refresh_from_db()
        self.assertEqual(obj.data, data)
        self.assertEqual(self.client.get(reverse("json_data_export", args=[obj.pk])).json(), data)

    def test_calculated_equivalents_keep_separate_groups_and_available_samples(self):
        """
        Derive equivalents without dropping zeros or borrowing another strain group

        A shorter stress component limits only its calculated equivalent curve.
        Total and plastic strain retain all samples in their original order.
        """
        owner = User.objects.create_user(username="calculated-curve-owner")
        self.client.force_login(owner)
        data = {}
        groups = (
            ("stress", "stress", [0, 1, 2, 1, 0]),
            ("total_strain", "strain", [0, 3e-6, 0.03, 0.015, 0]),
            ("plastic_strain", "plastic_strain", [0, 0, 0.015, 0.0075, 0]),
        )
        for group, prefix, normal_values in groups:
            data[group] = {f"{prefix}_11": normal_values}
            for component in ("22", "33", "12", "13", "23"):
                data[group][f"{prefix}_{component}"] = [0] * len(normal_values)
        data["stress"]["stress_23"] = [0] * 4
        obj = JSONData.objects.create(owner=owner, data=data)

        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))

        self.assertEqual(response.status_code, 200)
        variables = {variable["key"]: variable for variable in response.context["plot_variables"]}
        expected = {
            "stress.equivalent_stress": [0, 1, 2, 1],
            "total_strain.equivalent_strain": [0, 2e-6, 0.02, 0.01, 0],
            "plastic_strain.equivalent_plastic_strain": [0, 0, 0.01, 0.005, 0],
        }
        for key, values in expected.items():
            with self.subTest(key=key):
                variable = variables[key]
                self.assertTrue(variable["calculated"])
                self.assertEqual(len(variable["values"]), len(values))
                for actual, expected_value in zip(variable["values"], values):
                    self.assertAlmostEqual(actual, expected_value, places=15)
        for group, prefix, normal_values in groups:
            self.assertEqual(variables[f"{group}.{prefix}_11"]["values"], normal_values)
