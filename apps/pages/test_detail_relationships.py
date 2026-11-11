from copy import deepcopy

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import JSONData


class DetailRelationshipTests(TestCase):
    """
    Keep the relationship view grounded in one accessible object's metadata
    """

    @classmethod
    def setUpTestData(cls):
        """
        Create separate owners and readers for permission checks
        """
        cls.owner = User.objects.create_user(username="graph-owner")
        cls.reader = User.objects.create_user(username="graph-reader")

    def setUp(self):
        """
        Open detail pages as their owner by default
        """
        self.client.force_login(self.owner)

    def detail(self, data):
        """
        Read a stored record through its normal detail route

        Parameters
        ----------
        data : dict
            Uploaded metadata to retain unchanged.

        Returns
        -------
        tuple
            Record, rendered response and relationship graph.
        """
        obj = JSONData.objects.create(owner=self.owner, data=data)
        response = self.client.get(reverse("json_data_detail", args=[obj.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue("relationship_graph" in response.context, "Detail page must include its relationship graph")
        return obj, response, response.context["relationship_graph"]

    def test_models_stay_attached_to_their_own_phase(self):
        """
        Keep equal phase names distinct and retain each model's actual parent
        """
        _, _, graph = self.detail({
            "title": "Two phases", "creator": ["Alice", "Bob"], "software": "Abaqus",
            "phase": [
                {"phase_name": "Steel", "phase_id": 0, "constitutive_model": {
                    "elastic_model_name": "Isotropic elasticity",
                    "plastic_model_name": "Crystal plasticity",
                }},
                {"phase_name": "Steel", "phase_id": 2, "constitutive_model": {
                    "elastic_model_name": "Cubic elasticity",
                }},
            ],
        })
        phases = [node for node in graph["nodes"] if node["kind"] == "phase"]
        self.assertEqual([node["label"] for node in phases], ["Steel", "Steel"])
        self.assertNotEqual(phases[0]["id"], phases[1]["id"])
        models = [node for node in graph["nodes"] if node["kind"] == "model"]
        self.assertEqual([(node["label"], node["parent"]) for node in models], [
            ("Isotropic elasticity", phases[0]["id"]),
            ("Crystal plasticity", phases[0]["id"]),
            ("Cubic elasticity", phases[1]["id"]),
        ])
        self.assertIn({"label": "Phase ID", "value": "0"}, phases[0]["details"])

    def test_compatible_names_wrappers_and_descriptions_preserve_exports(self):
        """
        Recognize accepted field variants without changing original JSON
        """
        data = {
            "Identifier": ["graph-aliases"], "Title": "Aliased fields",
            "Creator Name": "Alice", "Other Creator Name": "Bob",
            "Software": [["DAMASK"]],
            "Phase": [{"Phase Name": ["Ferrite"], "Constitutive Model": [{
                "Elastic Model Name": ["Cubic elasticity"],
            }]}],
        }
        original = deepcopy(data)
        obj, response, graph = self.detail(data)
        labels = " | ".join(node["label"] for node in graph["nodes"])
        for value in ("Alice", "Bob", "DAMASK", "Ferrite", "Cubic elasticity"):
            self.assertIn(value, labels)
            self.assertContains(response, value)
        obj.refresh_from_db()
        self.assertEqual(obj.data, original)
        exported = self.client.get(reverse("json_data_export", args=[obj.pk]))
        self.assertEqual(exported.json(), original)

    def test_empty_or_unknown_metadata_does_not_invent_entities(self):
        """
        Ignore unrelated names and keep numeric IDs separate from phase names
        """
        _, response, graph = self.detail({
            "creator": [], "software": None,
            "custom": {"creator": "Hidden author", "phase_name": "Hidden phase"},
            "phase": [{"phase_id": 24}], "stress": {"stress_11": []},
        })
        self.assertEqual([node["kind"] for node in graph["nodes"]], ["record", "phase"])
        self.assertEqual(graph["nodes"][1]["label"], "Phase 1")
        self.assertNotIn("Hidden author", str(graph))
        self.assertNotIn("Hidden phase", str(graph))
        _, empty_response, empty = self.detail({"title": "No relationships"})
        self.assertEqual(len(empty["nodes"]), 1)
        self.assertContains(empty_response, "No related metadata is available")

    def test_results_reuse_curve_availability_without_copying_samples(self):
        """
        Show exact series lengths and distinguish supplied and calculated output
        """
        stress = {}
        for component in ("11", "22", "33", "12", "13", "23"):
            stress[f"stress_{component}"] = [0, 1, 2]
        stress["stress_11"] = [0, 1, 2, 3, 4]
        _, response, graph = self.detail({
            "title": "Output coverage", "stress": stress,
            "total_strain": {"equivalent_strain": [0, .1, .2, .3]},
            "plastic_strain": {"plastic_strain_11": []},
            "units": {"Stress": "MPa", "Strain": "1"},
        })
        outputs = [node for node in graph["nodes"] if node["kind"] == "output"]
        self.assertEqual([node["label"] for node in outputs], ["Stress", "Total strain"])
        text = str(outputs)
        self.assertIn("5 samples", text)
        self.assertIn("4 samples", text)
        self.assertIn("Calculated", text)
        self.assertIn("MPa", text)
        self.assertNotIn("'values':", text)
        self.assertContains(response, "Relationship details")

    def test_legacy_names_and_explicit_absence_do_not_become_false_models(self):
        """
        Retain legacy phase names while treating an explicit absence as a note
        """
        _, _, graph = self.detail({
            "phase": [None, {}, {"Name": "Legacy ferrite", "phase_id": 7,
                "constitutive_model": {"elastic_model_name": "Cubic elasticity",
                    "plastic_model_name": "  No plasticity in this elastic reference  ",
                    "damage_model_name": "Ductile damage"}}],
        })
        phases = [node for node in graph["nodes"] if node["kind"] == "phase"]
        self.assertEqual([node["label"] for node in phases], ["Legacy ferrite"])
        models = [node for node in graph["nodes"] if node["kind"] == "model"]
        self.assertEqual([node["label"] for node in models], ["Cubic elasticity", "Ductile damage"])
        self.assertIn({"label": "Plasticity", "value": "No plasticity in this elastic reference"},
                      phases[0]["details"])

    def test_graph_content_is_escaped_and_unrelated_records_are_excluded(self):
        """
        Keep uploaded HTML inert in SVG labels, titles and detail panels
        """
        attack = '<script>window.graphInjection = true</script>'
        JSONData.objects.create(owner=self.reader, data={"creator": "Other private creator"})
        _, response, graph = self.detail({"title": attack, "creator": attack})
        self.assertContains(response, "&lt;script&gt;window.graphInjection = true&lt;/script&gt;")
        self.assertNotContains(response, attack)
        self.assertNotIn("Other private creator", str(graph))
        self.assertNotContains(response, "Other private creator")

    def test_graph_obeys_existing_detail_access(self):
        """
        Require login and explicit access before returning relationship metadata
        """
        obj, _, _ = self.detail({"creator": "Private relationship creator"})
        url = reverse("json_data_detail", args=[obj.pk])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.reader)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 404)
        self.assertNotContains(denied, "Private relationship creator", status_code=404)
        obj.shared_users.add(self.reader)
        self.assertContains(self.client.get(url), "Private relationship creator")
        obj.shared_users.clear()
        obj.access_type = "all"
        obj.save(update_fields=["access_type"])
        self.assertContains(self.client.get(url), "Private relationship creator")
