import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.pages.models import JSONData


class ChartsAccessTests(TestCase):
    """
    Test chart data access rules
    """

    def setUp(self):
        """
        Create users used by chart tests
        """
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password",
        )
        self.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="password",
        )

    def _build_analysis_object_data(self, identifier):
        """
        Build a complete simulation object for chart analytics tests
        """
        return {
            "identifier": identifier,
            "phase": [
                {
                    "phase_identifier": "Copper",
                    "constitutive_model": {
                        "elastic_model_name": "Anisotropic Elasticity",
                        "elastic_parameters": {
                            "C11": 170000,
                            "C12": 124000,
                            "C44": 75000,
                        },
                        "plastic_model_name": "Crystal Plasticity",
                        "plastic_parameters": {
                            "initial_critical_resolved_shear_stress": 16,
                            "saturated_slip_resistance": 148,
                            "hardening_exponent": 2.5,
                            "reference_hardening_rate": 250,
                        },
                        "units": {
                            "Stress": "MPa",
                            "Stiffness": "MPa",
                        },
                    },
                }
            ],
            "software": "Abaqus CAE",
            "mechanical_BC": [
                {
                    "constraints": ["fixed", "loaded", "free"],
                    "loading_type": "force",
                    "loading_mode": "static",
                    "applied_load": [
                        {
                            "magnitude": -20,
                            "duration": 250,
                            "R": 0,
                        }
                    ],
                }
            ],
            "global_temperature": 300,
            "discretization_count": 12000,
            "RVE_size": [4, 4, 4],
            "RVE_continuity": True,
            "units": {
                "Force": "N",
                "Stress": "MPa",
                "Strain": 1,
                "Temperature": "Kelvin",
            },
            "stress": {
                "stress_11": [0, -12, -20],
            },
            "total_strain": {
                "strain_11": [0, 0.01, 0.02],
            },
            "plastic_strain": {
                "plastic_strain_11": [0, 0.001, 0.003],
            },
        }

    def test_charts_include_only_accessible_data_objects(self):
        """
        Charts exclude private data owned by another user
        """
        own_obj = JSONData.objects.create(
            owner=self.viewer,
            data={
                "identifier": "own-object",
                "phase": [
                    {
                        "phase_identifier": "Nickel",
                        "constitutive_model": {
                            "plastic_model_name": "Crystal Plasticity",
                        },
                    }
                ],
                "software": "DAMASK",
                "mechanical_BC": [
                    {
                        "constraints": ["fixed", "loaded", "fixed"],
                        "loading_type": "force",
                        "loading_mode": "static",
                    }
                ],
                "global_temperature": 298,
                "discretization_count": 1000,
                "RVE_continuity": True,
            },
            access_type="c",
        )
        public_obj = JSONData.objects.create(
            owner=self.owner,
            data={
                "identifier": "public-object",
                "phase": [
                    {
                        "phase_identifier": "Copper",
                        "constitutive_model": {
                            "plastic_model_name": "J2 Plasticity",
                        },
                    }
                ],
                "software": "Abaqus",
                "mechanical_BC": [
                    {
                        "constraints": ["loaded", "loaded", "fixed"],
                        "loading_type": "displacement",
                        "loading_mode": "static",
                    }
                ],
                "global_temperature": 300,
                "discretization_count": 2000,
                "RVE_continuity": False,
            },
            access_type="all",
        )
        shared_obj = JSONData.objects.create(
            owner=self.owner,
            data={
                "identifier": "shared-object",
                "phase": [
                    {
                        "phase_identifier": "Steel",
                        "constitutive_model": {
                            "plastic_model_name": "Crystal Plasticity",
                        },
                    }
                ],
                "software": "MOOSE",
                "mechanical_BC": [
                    {
                        "constraints": ["loaded", "free", "fixed"],
                        "loading_type": "force",
                        "loading_mode": "cyclic",
                    }
                ],
                "global_temperature": 310,
                "discretization_count": 3000,
                "RVE_continuity": True,
            },
            access_type="c",
        )
        JSONData.objects.create(
            owner=self.owner,
            data={
                "identifier": "hidden-object",
                "phase": [
                    {
                        "phase_identifier": "Hidden",
                        "constitutive_model": {
                            "plastic_model_name": "Hidden Model",
                        },
                    }
                ],
                "software": "HiddenSoft",
                "mechanical_BC": [
                    {
                        "constraints": ["hidden"],
                        "loading_type": "hidden-load",
                        "loading_mode": "hidden-mode",
                    }
                ],
            },
            access_type="c",
        )
        shared_obj.shared_users.add(self.viewer)

        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("charts"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_objects"], 3)
        self.assertEqual(response.context["phase_count"], 3)
        self.assertEqual(response.context["mechanical_bc_count"], 3)

        software_labels = json.loads(response.context["software_labels_json"])
        phase_labels = json.loads(response.context["phase_labels_json"])
        loading_type_labels = json.loads(response.context["loading_type_labels_json"])
        loading_mode_labels = json.loads(response.context["loading_mode_labels_json"])
        model_labels = json.loads(response.context["model_labels_json"])
        constraint_labels = json.loads(response.context["constraint_labels_json"])

        self.assertIn(own_obj.data["software"], software_labels)
        self.assertIn(public_obj.data["software"], software_labels)
        self.assertIn(shared_obj.data["software"], software_labels)
        self.assertNotIn("HiddenSoft", software_labels)
        self.assertNotIn("Hidden", phase_labels)
        self.assertIn("force", loading_type_labels)
        self.assertIn("displacement", loading_type_labels)
        self.assertIn("static", loading_mode_labels)
        self.assertIn("cyclic", loading_mode_labels)
        self.assertIn("Crystal Plasticity", model_labels)
        self.assertNotIn("Hidden Model", model_labels)
        self.assertNotIn("hidden-load", loading_type_labels)
        self.assertNotIn("Hidden", constraint_labels)

    def test_charts_build_domain_analysis_rows(self):
        """
        Charts build useful simulation analysis rows
        """
        JSONData.objects.create(
            owner=self.viewer,
            data=self._build_analysis_object_data("curve-a"),
            access_type="c",
        )
        JSONData.objects.create(
            owner=self.viewer,
            data=self._build_analysis_object_data("curve-b"),
            access_type="c",
        )
        JSONData.objects.create(
            owner=self.viewer,
            data={
                "identifier": "metadata-gap",
                "phase": "Copper",
            },
            access_type="c",
        )

        self.client.login(username="viewer", password="password")

        response = self.client.get(reverse("charts"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_objects"], 3)
        self.assertEqual(response.context["comparable_group_count"], 1)
        self.assertEqual(response.context["plot_ready_count"], 2)
        self.assertEqual(response.context["data_gap_count"], 1)

        comparable_group = response.context["comparable_group_rows"][0]
        self.assertEqual(comparable_group["objects"], 2)
        self.assertEqual(comparable_group["group_status"], "Comparable")
        self.assertEqual(comparable_group["ready_label"], "2 / 2")
        self.assertIn("Abaqus CAE", comparable_group["setup"])
        self.assertIn("Crystal Plasticity", comparable_group["setup"])

        response_rows = response.context["response_rows"]
        ready_rows = [row for row in response_rows if row["is_ready"]]
        self.assertEqual(len(ready_rows), 2)
        self.assertEqual(ready_rows[0]["points"], "3")
        self.assertEqual(ready_rows[0]["stress_peak"], "20 MPa")

        material_row = response.context["material_model_rows"][0]
        self.assertEqual(material_row["phase"], "Copper")
        self.assertEqual(material_row["objects"], 2)
        self.assertIn("C11 170,000 MPa", material_row["stiffness"])
        self.assertIn("CRSS 16 MPa", material_row["strength"])

        x_axis = response.context["constraint_matrix_rows"][0]
        self.assertEqual(x_axis["axis"], "X")
        self.assertEqual(x_axis["fixed"], 2)

        quality_rows = response.context["quality_rows"]
        stress_row = next(
            row for row in quality_rows if row["label"] == "Stress strain arrays"
        )
        self.assertEqual(stress_row["present"], 2)
        self.assertEqual(stress_row["missing"], 1)

        issue_rows = response.context["quality_issue_rows"]
        issue_labels = {row["label"] for row in issue_rows}
        self.assertIn("Software / solver", issue_labels)
        self.assertIn("metadata-gap", [row["example_label"] for row in issue_rows])

    def test_charts_prefer_phase_name_and_keep_legacy_phase_labels(self):
        """
        Use canonical phase names consistently across chart and material summaries
        """
        cases = (
            ({"phase_name": "Canonical Copper"}, "Canonical Copper", False),
            ({
                "phase_name": "Canonical Nickel",
                "phase_identifier": "Historical Nickel",
                "name": "Generic Nickel",
            }, "Canonical Nickel", False),
            ({"phase_name": "Canonical Iron", "name": "Generic Iron"}, "Canonical Iron", True),
            ({"phase_identifier": "Legacy Copper"}, "Legacy Copper", False),
            ({"name": "Legacy Silver"}, "Legacy Silver", True),
            ({"phase_name": "", "phase_identifier": "Legacy Tin"}, "Legacy Tin", False),
            ({"phase_name": "  \t", "phase_identifier": "Legacy Lead"}, "Legacy Lead", False),
        )
        objects = []
        for index, (phase_fields, expected, use_dict) in enumerate(cases):
            data = self._build_analysis_object_data(f"phase-name-chart-{index}")
            phase = {**phase_fields, "constitutive_model": data["phase"][0]["constitutive_model"]}
            data["phase"] = phase if use_dict else [phase]
            obj = JSONData.objects.create(owner=self.viewer, data=data)
            objects.append((obj, json.dumps(data)))
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("charts"))

        self.assertEqual(response.status_code, 200)
        expected_labels = {expected for _phase, expected, _use_dict in cases}
        self.assertEqual(set(json.loads(response.context["phase_labels_json"])), expected_labels)
        self.assertEqual(
            {row["phase"] for row in response.context["material_model_rows"]},
            expected_labels,
        )
        self.assertEqual(response.context["phase_count"], len(expected_labels))
        for obj, original in objects:
            obj.refresh_from_db()
            self.assertEqual(json.dumps(obj.data), original)
