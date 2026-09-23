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
            ("stress", "stress", "equivalent_stress", [0, 8], "stress", "MPa"),
            ("total_strain", "strain", "equivalent_strain", [0, 0.2], "strain", ""),
            ("plastic_strain", "plastic_strain", "equivalent_plastic_strain", [0, 0.1], "plastic_strain", ""),
        )
        for with_components in (False, True):
            with self.subTest(with_components=with_components):
                data = {"units": {"Stress": "MPa", "Strain": 1}}
                for group, prefix, key, values, _kind, _unit in groups:
                    data[group] = {key: values}
                    if with_components:
                        for component in ("11", "22", "33", "12", "13", "23"):
                            data[group][f"{prefix}_{component}"] = [0, 0]
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
