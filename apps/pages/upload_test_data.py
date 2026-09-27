from copy import deepcopy


def valid_upload_object(**changes):
    """
    Build synthetic metadata satisfying the platform's required field rules

    Each call returns independent containers for upload regression tests.

    Parameters
    ----------
    **changes : object
        Top level values to replace in the example.

    Returns
    -------
    dict
        One complete synthetic data object.
    """
    data = {
        "title": "Synthetic simulation", "creator": ["Researcher"],
        "creator_affiliation": ["Institute"], "date": "2026-09-27",
        "shared_with": [{"access_type": "c"}], "rights": "Reserved",
        "rights_holder": ["Researcher"], "software": "Solver", "software_version": "1",
        "system": "Linux", "system_version": "1", "processor_specifications": "CPU",
        "input_path": "inputs", "results_path": "results", "RVE_size": [1, 1, 1],
        "RVE_continuity": False, "discretization_type": "Structured",
        "discretization_unit_size": [1, 1, 1], "discretization_count": 1,
        "mechanical_BC": [{"vertex_list": ["V000"], "constraints": ["fixed", "free", "free"]}],
        "phase": [{"phase_name": "Copper", "constitutive_model": {"elastic_model_name": "Hooke"}}],
        "stress": {"equivalent_stress": [0, 1]}, "total_strain": {"equivalent_strain": [0, 0.01]},
        "units": {"Stress": "MPa", "Strain": 1, "Length": "mm", "Force": "N",
                  "Angle": "Radian", "Temperature": "K"},
    }
    data.update(deepcopy(changes))
    return data
