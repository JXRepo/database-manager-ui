"""
Validate and evaluate scientific field conditions and saved JSON selectors
"""

import json
import operator
import re
from decimal import Decimal, DecimalException, InvalidOperation, MAX_EMAX, MIN_EMIN, localcontext


MAX_CONDITIONS = 10
MAX_PATH_LENGTH = 1024
MAX_VALUE_LENGTH = 200
MAX_DEPTH = 32
DATA_FIELD_PRESETS = (
    ("texture_type", "Texture type", "text", "Microstructure"),
    ("grain_count", "Grain number", "number", "Microstructure"),
    ("lattice_structure", "Crystal structure", "text", "Microstructure"),
    ("orientation_identifier", "Orientation identifier", "text", "Microstructure"),
    ("discretization_type", "Discretization type", "text", "Discretization and boundaries"),
    ("discretization_count", "Discretization count", "number", "Discretization and boundaries"),
    ("RVE_continuity", "RVE continuity", "boolean", "Discretization and boundaries"),
    ("elastic_model_name", "Elastic model", "text", "Material models"),
    ("plastic_model_name", "Plastic model", "text", "Material models"),
    ("loading_type", "Loading type", "text", "Loading and temperature"),
    ("loading_mode", "Loading mode", "text", "Loading and temperature"),
    ("global_temperature", "Global temperature", "number", "Loading and temperature"),
)
DATA_FIELD_CHOICES = tuple((key, label) for key, label, field_type, group in DATA_FIELD_PRESETS)
DATA_FIELD_LABELS = dict(DATA_FIELD_CHOICES)
DATA_FIELD_GROUPS = {key: group for key, label, field_type, group in DATA_FIELD_PRESETS}
SAVED_PARAMETER_PATHS = {
    "elastic_parameters": ("phase", "constitutive_model", "elastic_parameters"),
    "plastic_parameters": ("phase", "constitutive_model", "plastic_parameters"),
}
# saved Ronak tokens keep their original named key meaning
LEGACY_FIELD_TYPES = {
    "Hash_Orientation": "text",
    "Texture_Type": "text",
    "Element_Number": "number",
    "Grain_Number": "number",
    "Material_parameters": "array",
    "Load_Type": "text",
    "Stress_Type": "text",
    "Load_Descriptor": "text",
    "Hash_load": "text",
    "Scaling_Factor": "number",
    "Max_Total_Strain": "number",
    "elastic_parameters": "parameters",
    "plastic_parameters": "parameters",
}
DATA_FIELD_TYPES = dict(LEGACY_FIELD_TYPES)
DATA_FIELD_TYPES.update({key: field_type for key, label, field_type, group in DATA_FIELD_PRESETS})
TECHNICAL_KEYS = {"$schema", "input_path", "results_path"}
NUMERIC_OPERATORS = {
    "eq": operator.eq,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}
OPERATOR_CHOICES = (
    ("contains", "Contains words"),
    ("exact", "Equals text"),
    ("eq", "Equals number"),
    ("gt", "Greater than"),
    ("gte", "Greater than or equal to"),
    ("lt", "Less than"),
    ("lte", "Less than or equal to"),
    ("between", "Between"),
    ("is", "Is"),
)
OPERATORS = {value for value, label in OPERATOR_CHOICES}
NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def get_field_option(field):
    """
    Describe a selectable preset or active saved field for the form

    Parameters
    ----------
    field : str
        Validated preset or legacy selector token.

    Returns
    -------
    dict
        Display group, type, default comparison, and input unit.
    """
    field_type = DATA_FIELD_TYPES[field]
    default_operator = {"number": "eq", "boolean": "is"}.get(field_type, "contains")
    if field == "orientation_identifier":
        default_operator = "exact"
    return {
        "value": field,
        "label": DATA_FIELD_LABELS.get(field, f"{field} (legacy key)"),
        "type": field_type,
        "group": DATA_FIELD_GROUPS.get(field, "Saved filters"),
        "default_operator": default_operator,
        "unit": "K" if field == "global_temperature" else "",
    }


def get_field_operators(field):
    """
    Return ordered comparison operators permitted for a named field

    The parser and form share these choices. Saved parameter objects support
    word searches only; legacy arrays and paths retain their original operators.

    Parameters
    ----------
    field : str
        Named catalog token, explicit JSON path, or unrecognized form value.

    Returns
    -------
    tuple of str
        Permitted operators in display order.
    """
    field_type = DATA_FIELD_TYPES.get(field)
    if field_type == "number":
        allowed = {"between", *NUMERIC_OPERATORS}
    elif field_type == "text":
        allowed = {"contains", "exact"}
    elif field_type == "parameters":
        allowed = {"contains"}
    elif field_type == "boolean":
        allowed = {"is"}
    else:
        allowed = OPERATORS - {"is"}
    return tuple(value for value, label in OPERATOR_CHOICES if value in allowed)


def _as_number(value):
    """
    Convert finite numeric scalars without floating point rounding

    Parameters
    ----------
    value : object
        A JSON scalar or submitted numeric string.

    Returns
    -------
    Decimal or None
        A finite number, excluding booleans and nonnumeric text.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value).strip()
    if not NUMBER_PATTERN.fullmatch(text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _searchable_key(key):
    """
    Exclude technical metadata keys consistently with basic search

    Parameters
    ----------
    key : object
        A dictionary key or submitted path component.

    Returns
    -------
    bool
        Whether the key can appear in a selectable field path.
    """
    if not isinstance(key, str) or not key or key.strip().casefold() in TECHNICAL_KEYS:
        return False
    try:
        key.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _parse_row(row):
    """
    Validate a single condition and prepare comparison values

    New presets select recursive scientific fields. Saved tokens retain their
    original meaning, and explicit JSON paths keep scalar matching only.

    Parameters
    ----------
    row : dict
        Raw strings retained for form correction.

    Returns
    -------
    dict
        Named key or exact path and comparison values for evaluation.

    Raises
    ------
    ValueError
        If the submitted path, operator, or comparison values are invalid.
    """
    if not row["field"]:
        raise ValueError("Choose a data field.")
    if len(row["field"]) > MAX_PATH_LENGTH:
        raise ValueError(f"The field path must be at most {MAX_PATH_LENGTH} characters.")
    if row["field"] in DATA_FIELD_LABELS:
        condition = {"preset": row["field"]}
    elif row["field"] in SAVED_PARAMETER_PATHS:
        condition = {"path": SAVED_PARAMETER_PATHS[row["field"]], "include_containers": True}
    elif row["field"] in LEGACY_FIELD_TYPES:
        condition = {"field_key": row["field"]}
    else:
        try:
            path = json.loads(row["field"])
        except (ValueError, RecursionError):
            raise ValueError("Choose a valid data field.") from None
        if not isinstance(path, list) or not path or len(path) > MAX_DEPTH:
            raise ValueError("Choose a valid data field.")
        if not all(_searchable_key(key) for key in path):
            raise ValueError("Choose a valid data field.")
        row["field"] = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
        condition = {"path": tuple(path)}
    operation = row["operator"]
    if operation not in OPERATORS:
        raise ValueError("Choose a valid comparison operator.")
    if operation not in get_field_operators(row["field"]):
        field_type = DATA_FIELD_TYPES.get(row["field"])
        if field_type == "number":
            raise ValueError(f"Choose a numeric comparison for {row['field']}.")
        if field_type == "boolean":
            raise ValueError("Choose Is for RVE continuity.")
        if field_type == "parameters":
            raise ValueError(f"Choose Contains words for {row['field']}.")
        if field_type not in {"text", "parameters"}:
            raise ValueError("Choose a supported comparison for this field.")
        raise ValueError(f"Choose Contains words or Equals text for {row['field']}.")
    if len(row["value"]) > MAX_VALUE_LENGTH or len(row["value_to"]) > MAX_VALUE_LENGTH:
        raise ValueError(f"Each value must be at most {MAX_VALUE_LENGTH} characters.")
    value = row["value"].strip()
    upper = row["value_to"].strip()
    if not value:
        raise ValueError("Enter a value for this condition.")
    if operation != "between" and upper:
        raise ValueError("An upper value is only allowed for a numeric range.")

    condition["operator"] = operation
    if operation == "is":
        if value not in {"true", "false"}:
            raise ValueError("Choose Periodic or Non-periodic for RVE continuity.")
        row["value"] = value
        condition["value"] = value == "true"
        return condition
    if operation in {"contains", "exact"}:
        condition["value"] = value.casefold()
        return condition

    number = _as_number(value)
    if number is None:
        raise ValueError("Enter a finite number without units.")
    condition["value"] = number
    if operation == "between":
        upper_number = _as_number(upper)
        if upper_number is None:
            raise ValueError("Enter a finite upper number for the range.")
        if upper_number < number:
            raise ValueError("The upper number must be greater than or equal to the lower number.")
        condition["value_to"] = upper_number
    if row["field"] == "global_temperature":
        if number < 0 or (operation == "between" and condition["value_to"] < 0):
            raise ValueError("Enter a temperature at or above 0 K.")
    return condition


def parse_conditions(query):
    """
    Parse repeated form parameters into rows and validated conditions

    Parameters
    ----------
    query : QueryDict
        Submitted search parameters.

    Returns
    -------
    tuple
        Form rows, validated conditions, and user facing errors. Any error
        clears all conditions; callers must not run a search when errors exist.
    """
    columns = {}
    for name in ("field", "operator", "value", "value_to"):
        columns[name] = query.getlist("condition_" + name)
    count = max(len(values) for values in columns.values())
    errors = []
    if count > MAX_CONDITIONS:
        errors.append(f"Use at most {MAX_CONDITIONS} field conditions.")
    for name, values in columns.items():
        if name == "value_to" and not values:
            continue
        if len(values) != count:
            errors.append("Some condition fields are missing. Review each condition and try again.")
            break

    rows = []
    conditions = []
    for index in range(min(count, MAX_CONDITIONS)):
        row = {"error": ""}
        for name, values in columns.items():
            row[name] = values[index] if index < len(values) else ""
        if not any(row[name].strip() for name in ("field", "value", "value_to")):
            if row["operator"] in ("", "contains"):
                continue
        try:
            condition = _parse_row(row)
        except ValueError as error:
            row["error"] = str(error)
            errors.append(f"Condition {index + 1}: {error}")
        else:
            conditions.append(condition)
        rows.append(row)
    return rows, [] if errors else conditions, errors


def _field_values(data, path, depth=0, include_containers=False):
    """
    Yield values at an exact path with transparent array traversal

    Presets can search parameter dictionaries as text. Explicit bookmarked
    paths retain the original scalar candidates unless containers are requested.

    Parameters
    ----------
    data : object
        Current JSON value.
    path : tuple of str
        Remaining dictionary keys to traverse.
    depth : int, optional
        Current nesting depth, including arrays.
    include_containers : bool, optional
        Include complete dictionaries and arrays at the selected path.

    Yields
    ------
    object
        Nonnull candidates at the requested path only.
    """
    if depth > MAX_DEPTH:
        return
    if not path and include_containers and isinstance(data, (dict, list)):
        yield data
    if isinstance(data, list):
        for value in data:
            yield from _field_values(value, path, depth + 1, include_containers)
    elif path:
        if isinstance(data, dict) and path[0] in data:
            yield from _field_values(data[path[0]], path[1:], depth + 1, include_containers)
    elif data is not None and not isinstance(data, dict):
        yield data


def _named_field_values(data, field_key, depth=0):
    """
    Yield values whose complete dictionary key matches a selected field

    Containers remain available for text matching. Array scalars also remain
    separate candidates for numeric comparisons.

    Parameters
    ----------
    data : object
        Current JSON value.
    field_key : str
        Selected key with case folding already applied.
    depth : int, optional
        Current nesting depth, including arrays.

    Yields
    ------
    object
        Nonnull matching values and their array scalars.
    """
    if depth >= MAX_DEPTH:
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if key.casefold() == field_key:
                if isinstance(value, (dict, list)):
                    yield value
                yield from _field_values(value, (), depth + 1)
            yield from _named_field_values(value, field_key, depth + 1)
    elif isinstance(data, list):
        for value in data:
            yield from _named_field_values(value, field_key, depth + 1)


def _normalize_field_name(key):
    """
    Normalize spelling separators without guessing semantic aliases

    Parameters
    ----------
    key : str
        JSON dictionary key.

    Returns
    -------
    str
        Case folded name without whitespace, underscores, or hyphens.
    """
    return re.sub(r"[\s_-]+", "", key).casefold()


def _enclosing_temperature_unit(data, inherited):
    """
    Read a local temperature unit without borrowing sibling metadata

    Parameters
    ----------
    data : dict
        Current JSON object.
    inherited : object
        Temperature unit declared by an enclosing object, if any.

    Returns
    -------
    object
        Local declaration or the inherited unit. Ambiguous declarations
        return None rather than selecting a unit by dictionary order.
    """
    declarations = [value for key, value in data.items() if _normalize_field_name(key) == "units"]
    if not declarations:
        return inherited
    if len(declarations) != 1 or not isinstance(declarations[0], dict):
        return None
    units = [value for key, value in declarations[0].items() if _normalize_field_name(key) == "temperature"]
    if not units:
        return inherited
    return units[0] if len(units) == 1 else None


def _temperature_in_kelvin(value, unit):
    """
    Convert a finite temperature with an explicit supported unit to kelvin

    Parameters
    ----------
    value : object
        Stored numeric scalar or numeric string.
    unit : object
        Kelvin, Celsius, or Fahrenheit unit declaration.

    Returns
    -------
    Decimal or None
        Converted temperature, excluding missing units and values below
        absolute zero. Invalid arithmetic does not interrupt a search.
    """
    number = _as_number(value)
    if number is None or not isinstance(unit, str):
        return None
    unit = re.sub(r"[\s°]+", "", unit).casefold()
    try:
        with localcontext() as context:
            context.prec = MAX_VALUE_LENGTH + 16
            context.Emax = MAX_EMAX
            context.Emin = MIN_EMIN
            if unit in {"k", "kelvin", "kelvins"}:
                temperature = number
            elif unit in {"c", "celsius", "degc", "degreecelsius", "degreescelsius"}:
                temperature = number + Decimal("273.15")
            elif unit in {"f", "fahrenheit", "degf", "degreefahrenheit", "degreesfahrenheit"}:
                temperature = (number - Decimal("32")) * Decimal("5") / Decimal("9") + Decimal("273.15")
            else:
                return None
    except DecimalException:
        return None
    return temperature if temperature.is_finite() and temperature >= 0 else None


def _preset_field_values(data, field, depth=0, in_mechanical=False, temperature_unit=None):
    """
    Find preset values recursively while preserving scientific context

    Loading selectors exclude thermal boundary conditions. Temperature units
    follow the enclosing objects, never another phase or sibling branch.

    Parameters
    ----------
    data : object
        Current JSON value.
    field : str
        Validated scientific preset token.
    depth : int, optional
        Current recursion depth, including arrays.
    in_mechanical : bool, optional
        Whether this branch belongs to mechanical boundary conditions.
    temperature_unit : object, optional
        Inherited temperature unit.

    Yields
    ------
    object
        Scalar candidates of the preset's type. Temperatures are in kelvin.
    """
    if depth >= MAX_DEPTH:
        return
    if isinstance(data, list):
        for item in data:
            yield from _preset_field_values(item, field, depth + 1, in_mechanical, temperature_unit)
        return
    if not isinstance(data, dict):
        return
    if field == "global_temperature":
        temperature_unit = _enclosing_temperature_unit(data, temperature_unit)
    names = {_normalize_field_name(field)}
    if field == "grain_count":
        names.add("grainnumber")
    mechanical_only = field in {"loading_type", "loading_mode"}
    field_type = DATA_FIELD_TYPES[field]
    for key, value in data.items():
        name = _normalize_field_name(key)
        if mechanical_only and name == "thermalbc":
            continue
        if name in names and (not mechanical_only or in_mechanical):
            for candidate in _field_values(value, (), depth + 1):
                if field == "global_temperature":
                    candidate = _temperature_in_kelvin(candidate, temperature_unit)
                    if candidate is not None:
                        yield candidate
                elif field_type == "text" and isinstance(candidate, str):
                    yield candidate
                elif field_type == "boolean" and isinstance(candidate, bool):
                    yield candidate
                elif field_type == "number":
                    yield candidate
        yield from _preset_field_values(
            value, field, depth + 1, in_mechanical or name == "mechanicalbc", temperature_unit,
        )


def _matches_condition(data, condition):
    """
    Evaluate one prepared comparison against matching field values

    Presets match typed scalar values. Saved named fields and paths retain
    their previous container and numeric matching rules.

    Parameters
    ----------
    data : object
        Stored JSON value.
    condition : dict
        Validated field selector, operator, and comparison values.

    Returns
    -------
    bool
        Whether the condition matches appropriate candidates.
    """
    operation = condition["operator"]
    expected = condition["value"]
    if "preset" in condition:
        values = _preset_field_values(data, condition["preset"])
    elif "field_key" in condition:
        values = _named_field_values(data, condition["field_key"].casefold())
    else:
        values = _field_values(data, condition["path"], include_containers=condition.get("include_containers", False))
    if operation == "is":
        return any(value is expected for value in values)
    if operation == "contains":
        remaining = set(expected.split())
        for value in values:
            text = str(value).casefold()
            remaining = {term for term in remaining if term not in text}
            if not remaining:
                return True
        return False
    if operation == "exact":
        return any(str(value).strip().casefold() == expected for value in values)
    for value in values:
        number = value if isinstance(value, Decimal) else _as_number(value)
        if number is None:
            continue
        if operation == "between":
            if expected <= number <= condition["value_to"]:
                return True
        elif NUMERIC_OPERATORS[operation](number, expected):
            return True
    return False


def matches_conditions(data, conditions):
    """
    Check whether all validated conditions match the stored JSON

    Parameters
    ----------
    data : object
        Stored JSON value.
    conditions : list of dict
        Validated conditions from ``parse_conditions``.

    Returns
    -------
    bool
        Whether every condition matches.
    """
    return all(_matches_condition(data, condition) for condition in conditions)
