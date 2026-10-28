from copy import deepcopy

from django.test import SimpleTestCase

from .boundary_deformation import deformation_context


class BoundaryDeformationContextTests(SimpleTestCase):
    """
    Keep deformation inputs narrow and independent of stored metadata
    """

    def test_context_uses_explicit_single_phase_parameters_without_large_arrays(self):
        """
        Extract geometry and explicit elastic parameters without changing input
        """
        data = {"RVE_size": [2, 2, 2], "units": {"Length": "mm"}, "phase": [{
            "orientation": {"large_array": list(range(100))}, "volume_fraction": 1,
            "constitutive_model": {"elastic_model_name": "Isotropic linear elasticity",
                "elastic_parameters": {"youngs_modulus": "120000", "poisson_ratio": .34},
                "units": {"Stiffness": "MPa"}}}]}
        original = deepcopy(data)
        result = deformation_context(data)
        self.assertEqual(result["size"], [2, 2, 2])
        self.assertEqual(result["phaseCount"], 1)
        self.assertEqual(result["model"]["youngsModulus"], 120000)
        self.assertEqual(result["model"]["stiffnessUnit"], "MPa")
        self.assertNotIn("large_array", str(result))
        self.assertEqual(data, original)

    def test_multiple_phases_and_invalid_parameter_values_are_not_chosen(self):
        """
        Preserve insufficient material information instead of selecting a phase
        """
        self.assertIsNone(deformation_context({"phase": [{}, {}]})["model"])
        result = deformation_context({"phase": [{"constitutive_model": {
            "elastic_parameters": {"youngs_modulus": True, "poisson_ratio": "NaN"}}}]})
        self.assertIsNone(result["model"]["youngsModulus"])
        self.assertIsNone(result["model"]["poissonRatio"])
