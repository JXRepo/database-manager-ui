"""
Keep metadata display order independent of database JSON key order
"""

# Main fields follow mandatory_fields in MiMeDat metadata_template.py
# Nested fields follow required declarations in MiMeDat and its referenced schemas
# https://github.com/Ronakshoghi/MiMeDat/blob/511cb98b02270d7f31b55243ff49cfef6c7b240d/microstructure_sensitive_mechanical_metadata_schema.json
# These lists guide presentation only; they do not validate uploaded data
VISUALIZED_DETAIL_FIELDS = frozenset({"mechanical_BC", "stress", "total_strain"})

DETAIL_FIELD_ORDERS = {
    "": (
        "title", "creator", "creator_affiliation", "date", "shared_with",
        "rights", "rights_holder", "software", "software_version", "system",
        "system_version", "processor_specifications", "input_path", "results_path",
        "RVE_size", "RVE_continuity",
        "discretization_type", "discretization_unit_size", "discretization_count",
        "mechanical_BC", "phase", "stress", "total_strain", "units",
    ),
    "shared_with": ("access_type",),
    "mechanical_BC": ("vertex_list", "constraints"),
    "mechanical_BC.applied_load": ("magnitude",),
    "mechanical_BC.applied_load.magnitude": (
        "xx", "yy", "zz", "xy", "yz", "xz",
    ),
    "thermal_BC": ("vertex_list", "constraints"),
    "thermal_BC.applied_load": ("magnitude",),
    "phase": ("phase_name", "constitutive_model"),
    "phase.orientation": ("euler_angles", "grain_count", "texture_type"),
    "phase.orientation.euler_angles": ("Phi1", "Phi", "Phi2"),
    "microstructure": ("time_point", "grid", "voxels"),
    "microstructure.grid": ("status", "grid_size", "grid_spacing"),
    "microstructure.grains": ("grain_id", "phase_id", "orientation"),
    "microstructure.voxels": (
        "voxel_id", "phase_id", "centroid_coordinates", "voxel_index", "orientation",
    ),
    "units": ("Stress", "Strain", "Length", "Force", "Angle", "Temperature"),
}

DETAIL_FIELD_RANKS = {}
for _path, _fields in DETAIL_FIELD_ORDERS.items():
    _parts = tuple(_path.split(".")) if _path else ()
    DETAIL_FIELD_RANKS[_parts] = {name: index for index, name in enumerate(_fields)}


def detail_field_rank(name, path=(), data=None):
    """
    Find a field's display position within its metadata object

    Array indices do not affect the order of fields inside each item.
    Required fields come first. Other fields retain their relative stored order.
    Conditional requirements only affect presentation and never reject data.

    Parameters
    ----------
    name : str
        Original field name from the stored JSON.
    path : tuple, optional
        Original parent keys and array indices used while building detail rows.
    data : dict, optional
        Parent object used to determine applicable sharing and thermal conditions.

    Returns
    -------
    int
        Required field position, or the following position for other fields.
    """
    path = tuple(part for part in path if not isinstance(part, int))
    ranks = DETAIL_FIELD_RANKS.get(path, {})
    if isinstance(data, dict):
        if path == ("shared_with",) and data.get("access_type") in ("u", "g"):
            ranks = {**ranks, "access_list": 1}
        elif path == ("thermal_BC",):
            constraints = data.get("constraints")
            if isinstance(constraints, list) and "loaded" in constraints:
                ranks = {**ranks, "loading_mode": 2, "applied_load": 3}
    return ranks.get(name, len(ranks))


def ordered_metadata_items(data, path=()):
    """
    Order dictionary fields for display without modifying the stored object

    Required children precede other fields within the same object.

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
    return sorted(data.items(), key=lambda item: detail_field_rank(item[0], path, data))
