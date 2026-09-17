"""
Validate and evaluate bounded conditions against preset JSON paths or legacy keys
"""

import json
import operator
import re
from decimal import Decimal, InvalidOperation


MAX_CONDITIONS = 10
MAX_PATH_LENGTH = 1024
MAX_VALUE_LENGTH = 200
MAX_DEPTH = 32
DATA_FIELD_PRESETS = (
    ("orientation_identifier", "Orientation identifier", "text",
     ("phase", "orientation", "orientation_identifier")),
    ("texture_type", "Texture type", "text", ("phase", "orientation", "texture_type")),
    ("grain_count", "Grain count", "number", ("phase", "orientation", "grain_count")),
    ("discretization_count", "Discretization count", "number", ("discretization_count",)),
    ("elastic_model_name", "Elastic model", "text", ("phase", "constitutive_model", "elastic_model_name")),
    ("elastic_parameters", "Elastic parameters", "parameters", ("phase", "constitutive_model", "elastic_parameters")),
    ("plastic_model_name", "Plastic model", "text", ("phase", "constitutive_model", "plastic_model_name")),
    ("plastic_parameters", "Plastic parameters", "parameters", ("phase", "constitutive_model", "plastic_parameters")),
    ("loading_type", "Loading type", "text", ("mechanical_BC", "loading_type")),
    ("loading_mode", "Loading mode", "text", ("mechanical_BC", "loading_mode")),
    ("global_temperature", "Global temperature", "number", ("global_temperature",)),
)
DATA_FIELD_CHOICES = tuple((key, label) for key, label, field_type, path in DATA_FIELD_PRESETS)
DATA_FIELD_PATHS = {key: path for key, label, field_type, path in DATA_FIELD_PRESETS}
# saved Ronak tokens keep their original named key meaning, not aliases to new paths
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
}
DATA_FIELD_TYPES = dict(LEGACY_FIELD_TYPES)
DATA_FIELD_TYPES.update({key: field_type for key, label, field_type, path in DATA_FIELD_PRESETS})
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
    ("gte", "At least"),
    ("lt", "Less than"),
    ("lte", "At most"),
    ("between", "Between"),
)
OPERATORS = {value for value, label in OPERATOR_CHOICES}
NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def get_field_operators(field):
    """
    Return ordered comparison operators permitted for a named field

    The parser and form share these choices. Parameter objects support word
    searches only; legacy arrays and paths retain every original operator.

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
    else:
        allowed = OPERATORS
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

    New presets select schema paths. Saved tokens retain their original named
    key meanings, and explicit JSON paths keep scalar matching only.

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
    if row["field"] in DATA_FIELD_PATHS:
        condition = {"path": DATA_FIELD_PATHS[row["field"]], "include_containers": True}
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
        if DATA_FIELD_TYPES[row["field"]] == "number":
            raise ValueError(f"Choose a numeric comparison for {row['field']}.")
        if DATA_FIELD_TYPES[row["field"]] == "parameters":
            raise ValueError(f"Choose Contains words for {row['field']}.")
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


def _matches_condition(data, condition):
    """
    Evaluate one prepared comparison against matching field values

    Presets and legacy named fields include complete containers for text
    matching. Explicit paths retain their existing scalar matching rules.

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
    if "field_key" in condition:
        values = _named_field_values(data, condition["field_key"].casefold())
    else:
        values = _field_values(data, condition["path"], include_containers=condition.get("include_containers", False))
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
        number = _as_number(value)
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
