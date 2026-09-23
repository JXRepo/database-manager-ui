"""
Keep metadata display order independent of database JSON key order
"""

# Fields follow properties declarations in MiMeDat and its referenced schemas
# Supplied root header fields precede properties in schema document order
# https://github.com/Ronakshoghi/MiMeDat/blob/511cb98b02270d7f31b55243ff49cfef6c7b240d/microstructure_sensitive_mechanical_metadata_schema.json
# https://raw.githubusercontent.com/Ronakshoghi/MetadataSchema/main/general_constitutive_model_metadata_schema.json
# https://raw.githubusercontent.com/YousefRezek/MicrostructureEvolutionDataSchema/main/Microstructure_Module.json
# These lists guide presentation only; they do not validate uploaded data
VISUALIZED_DETAIL_FIELDS = frozenset({
    "mechanical_BC", "stress", "total_strain", "plastic_strain",
})

DETAIL_FIELD_ORDERS = {
    "": (
        "$schema", "$id", "version", "type", "description",
        "identifier", "title", "creator", "creator_ORCID", "creator_affiliation",
        "creator_institute", "creator_group", "contributor", "contributor_ORCID",
        "contributor_affiliation", "contributor_institute", "contributor_group",
        "date", "shared_with", "rights", "rights_holder",
        "funder_name", "fund_identifier", "publisher", "relation",
        "user_extra_information", "keywords", "software", "software_version",
        "system", "system_version", "processor_specifications", "input_path",
        "results_path", "system_extra_information", "RVE_size", "RVE_continuity",
        "discretization_type", "discretization_unit_size", "discretization_count",
        "solid_volume_fraction", "origin", "global_temperature", "mechanical_BC",
        "thermal_BC", "phase", "microstructure", "stress", "total_strain",
        "plastic_strain", "units",
    ),
    "shared_with": ("access_type", "access_list"),
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
        "phase_name", "phase_id", "volume_fraction", "lattice_structure",
        "constitutive_model", "orientation",
    ),
    "phase.constitutive_model": (
        "$schema", "elastic_model_name", "elastic_parameters", "plastic_model_name",
        "plastic_parameters", "damage_model_name", "damage_parameters",
    ),
    "phase.orientation": (
        "euler_angles", "grain_count", "texture_type", "frame", "rotation_type",
        "software", "software_version", "orientation_identifier",
        "texture_extra_information",
    ),
    "phase.orientation.euler_angles": ("Phi1", "Phi", "Phi2"),
    "microstructure": ("microstructure_state_id", "time_point", "grid", "grains", "voxels"),
    "microstructure.grid": ("status", "grid_size", "grid_spacing"),
    "microstructure.grains": ("grain_id", "phase_id", "grain_volume", "orientation", "parent_grain_id"),
    "microstructure.voxels": (
        "voxel_id", "grain_id", "phase_id", "centroid_coordinates", "voxel_index",
        "voxel_volume", "orientation", "deformation_gradient",
        "first_piola_kirchhoff_stress", "strain", "IPFcolor_(1 0 0)",
    ),
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

DETAIL_FIELD_RANKS = {}
for _path, _fields in DETAIL_FIELD_ORDERS.items():
    _parts = tuple(_path.split(".")) if _path else ()
    DETAIL_FIELD_RANKS[_parts] = {name: index for index, name in enumerate(_fields)}


def detail_field_rank(name, path=()):
    """
    Find a field's display position within its metadata object

    Array indices do not affect the order of fields inside each item.
    Defined fields follow properties order, regardless of whether they are required.
    Other fields retain their relative stored order after defined fields.

    Parameters
    ----------
    name : str
        Original field name from the stored JSON.
    path : tuple, optional
        Original parent keys and array indices used while building detail rows.

    Returns
    -------
    int
        Schema field position, or the following position for other fields.
    """
    path = tuple(part for part in path if not isinstance(part, int))
    ranks = DETAIL_FIELD_RANKS.get(path, {})
    return ranks.get(name, len(ranks))


def ordered_metadata_items(data, path=()):
    """
    Order dictionary fields for display without modifying the stored object

    Schema children precede custom fields within the same object. Sorting stays
    stable so custom fields keep their relative stored order.

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
