"""
Keep metadata display order independent of database JSON key order
"""

# Main fields follow mandatory_fields in MiMeDat metadata_template.py
# Nested order is retained from MiMeDat 511cb98b02270d7f31b55243ff49cfef6c7b240d
# https://github.com/Ronakshoghi/MiMeDat/blob/511cb98b02270d7f31b55243ff49cfef6c7b240d/microstructure_sensitive_mechanical_metadata_schema.json
# These lists guide presentation only; they do not validate uploaded data
DETAIL_FIELD_ORDERS = {
    "": (
        "title", "creator", "creator_affiliation", "date", "shared_with",
        "rights", "rights_holder", "software", "software_version", "system",
        "system_version", "processor_specifications", "input_path", "results_path",
        "RVE_size", "RVE_continuity",
        "discretization_type", "discretization_unit_size", "discretization_count",
        "mechanical_BC", "phase", "stress", "total_strain", "units",
    ),
    "shared_with": ("access_type", "access_list", "username"),
    "origin": (
        "software", "software_version", "system", "system_version",
        "input_path", "results_path",
    ),
    "mechanical_BC": (
        "vertex_list", "constraints", "loading_type", "loading_mode", "applied_load",
    ),
    "mechanical_BC.applied_load": ("magnitude", "frequency", "duration", "R", "step"),
    "mechanical_BC.applied_load.magnitude": (
        "xx", "yy", "zz", "xy", "yx", "xz", "zx", "yz", "zy",
    ),
    "thermal_BC": ("vertex_list", "constraints", "loading_mode", "applied_load"),
    "thermal_BC.applied_load": ("magnitude", "frequency", "duration"),
    "phase": (
        "phase_name", "phase_id", "phase_identifier", "volume_fraction",
        "lattice_structure", "constitutive_model", "orientation",
    ),
    "phase.constitutive_model": (
        "$schema", "elastic_model_name", "elastic_parameters", "plastic_model_name",
        "plastic_parameters", "damage_model_name", "damage_parameters",
        "interatomic_potential_name", "interatomic_potential_parameters",
        "defect_model_name", "defect_parameters", "deformation_model_name",
        "deformation_parameters", "units",
    ),
    "phase.orientation": (
        "euler_angles", "grain_count", "texture_type", "frame", "rotation_type",
        "software", "software_version", "orientation_identifier", "texture_extra_information",
    ),
    "phase.orientation.euler_angles": ("Phi1", "Phi", "Phi2"),
    "stress": (
        "equivalent_stress", "stress_11", "stress_22", "stress_33",
        "stress_12", "stress_13", "stress_23",
    ),
    "total_strain": (
        "equivalent_strain", "strain_11", "strain_22", "strain_33",
        "strain_12", "strain_13", "strain_23",
    ),
    "plastic_strain": (
        "equivalent_plastic_strain", "plastic_strain_11", "plastic_strain_22",
        "plastic_strain_33", "plastic_strain_12", "plastic_strain_13", "plastic_strain_23",
    ),
    "units": ("Stress", "Strain", "Length", "Force", "Angle", "Temperature"),
}

# Keep documented older nested spellings in position without renaming them
DETAIL_FIELD_ALIASES = {
    "origin": {
        "software Version": "software_version",
        "system Version": "system_version",
        "Input Path": "input_path",
        "Results Path": "results_path",
    },
    "phase.constitutive_model": {"schema": "$schema"},
    "thermal_BC": {"vertices_list": "vertex_list"},
}

DETAIL_FIELD_RANKS = {}
for _path, _fields in DETAIL_FIELD_ORDERS.items():
    _parts = tuple(_path.split(".")) if _path else ()
    DETAIL_FIELD_RANKS[_parts] = {name: index for index, name in enumerate(_fields)}
DETAIL_FIELD_ALIASES = {
    tuple(path.split(".")) if path else (): aliases
    for path, aliases in DETAIL_FIELD_ALIASES.items()
}


def detail_field_rank(name, path=()):
    """
    Find a field's display position within its metadata object

    Array indices do not affect the order of fields inside each item.
    Unknown fields share the last position so stable sorting retains them.

    Parameters
    ----------
    name : str
        Original field name from the stored JSON.
    path : tuple, optional
        Original parent keys and array indices used while building detail rows.

    Returns
    -------
    int
        Schema position, or the number of known fields for an unknown field.
    """
    path = tuple(part for part in path if not isinstance(part, int))
    ranks = DETAIL_FIELD_RANKS.get(path, {})
    name = DETAIL_FIELD_ALIASES.get(path, {}).get(name, name)
    return ranks.get(name, len(ranks))


def ordered_metadata_items(data, path=()):
    """
    Order dictionary fields for display without modifying the stored object

    Unknown children remain after known fields in their existing group.

    Parameters
    ----------
    data : dict
        Metadata dictionary whose fields will be displayed.
    path : tuple, optional
        Original parent keys and array indices used while building detail rows.

    Returns
    -------
    list of tuple
        Original keys and values in their display order.
    """
    return sorted(data.items(), key=lambda item: detail_field_rank(item[0], path))
