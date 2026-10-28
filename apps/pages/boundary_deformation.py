import math

from apps.dyn_api.metadata_compat import field_value


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
    result["model"] = {
        "name": model.get("elastic_model_name"),
        "youngsModulus": _number(field_value(parameters, "youngs_modulus")),
        "poissonRatio": _number(field_value(parameters, "poisson_ratio")),
        "stiffnessUnit": field_value(model.get("units"), "Stiffness"),
    }
    return result
