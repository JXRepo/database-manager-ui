import math

from apps.dyn_api.metadata_compat import field_name, field_value


def _number(value):
    """
    Read a finite explicit material parameter

    Parameters
    ----------
    value : object
        Numeric value or numeric text from metadata.

    Returns
    -------
    float or None
        Finite number, excluding booleans and containers.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _consistent_value(data, name, parse):
    """
    Read a freeform functional field only when its matching names agree

    Parameters
    ----------
    data : object
        Parent metadata dictionary.
    name : str
        Explicit parameter or unit field name.
    parse : callable
        Convert one supplied value, returning None when invalid.

    Returns
    -------
    tuple
        Parsed value and whether duplicate spellings conflict or are invalid.
    """
    if not isinstance(data, dict):
        return None, False
    values = [parse(value) for key, value in data.items() if field_name(key) == field_name(name)]
    compared = [value.casefold() if isinstance(value, str) else value for value in values]
    if len(values) > 1 and (any(value is None for value in values)
                           or any(value != compared[0] for value in compared[1:])):
        return None, True
    return (values[0] if values else None), False


def deformation_context(metadata):
    """
    Extract compact inputs for a homogeneous elastic deformation preview

    Parameters
    ----------
    metadata : dict
        Shared metadata compatibility view for an accessible data object.

    Returns
    -------
    dict
        Geometry and explicit single phase parameters, without large arrays.
    """
    phases = metadata.get("phase")
    phases = phases if isinstance(phases, list) else [phases] if isinstance(phases, dict) else []
    size = metadata.get("RVE_size")
    result = {
        "size": [_number(value) for value in size] if isinstance(size, list) and len(size) == 3 else None,
        "lengthUnit": field_value(metadata.get("units"), "Length"),
        "solidFraction": _number(metadata.get("solid_volume_fraction")),
        "phaseCount": len(phases), "model": None,
    }
    if len(phases) != 1 or not isinstance(phases[0], dict):
        return result
    phase = phases[0]
    model = phase.get("constitutive_model")
    model = model if isinstance(model, dict) else {}
    parameters = model.get("elastic_parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    result["phaseFraction"] = _number(phase.get("volume_fraction"))
    model_units, units_conflict = _consistent_value(
        model, "units", lambda value: value if isinstance(value, dict) else None)
    conflicts = ["units"] if units_conflict else []
    result["model"] = {"name": model.get("elastic_model_name")}
    for output, parent, name, parse in (
        ("youngsModulus", parameters, "youngs_modulus", _number),
        ("poissonRatio", parameters, "poisson_ratio", _number),
        ("stiffnessUnit", model_units, "Stiffness",
         lambda value: value.strip() if isinstance(value, str) else None),
    ):
        value, conflict = _consistent_value(parent, name, parse)
        result["model"][output] = value
        if conflict:
            conflicts.append(name)
    if conflicts:
        result["error"] = ("Conflicting material values for " + ", ".join(conflicts)
                           + ". Keep one consistent value for each parameter before estimating deformation.")
    return result
