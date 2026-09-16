"""
Validate and evaluate bounded conditions against exact JSON field paths
"""

import json
import operator
import re
from decimal import Decimal, InvalidOperation


MAX_CONDITIONS = 10
MAX_PATH_LENGTH = 1024
MAX_VALUE_LENGTH = 200
MAX_DEPTH = 32
TECHNICAL_KEYS = {"$schema", "input_path", "results_path"}
NUMERIC_OPERATORS = {
    "eq": operator.eq,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}
OPERATORS = {"contains", "exact", "between", *NUMERIC_OPERATORS}
NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


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

    Parameters
    ----------
    row : dict
        Raw strings retained for form correction.

    Returns
    -------
    dict
        Exact path and comparison values for evaluation.

    Raises
    ------
    ValueError
        If the submitted path, operator, or comparison values are invalid.
    """
    if not row["field"]:
        raise ValueError("Choose a data field.")
    if len(row["field"]) > MAX_PATH_LENGTH:
        raise ValueError(f"The field path must be at most {MAX_PATH_LENGTH} characters.")
    try:
        path = json.loads(row["field"])
    except (ValueError, RecursionError):
        raise ValueError("Choose a valid data field.") from None
    if not isinstance(path, list) or not path or len(path) > MAX_DEPTH:
        raise ValueError("Choose a valid data field.")
    if not all(_searchable_key(key) for key in path):
        raise ValueError("Choose a valid data field.")
    row["field"] = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
    operation = row["operator"]
    if operation not in OPERATORS:
        raise ValueError("Choose a valid comparison operator.")
    if len(row["value"]) > MAX_VALUE_LENGTH or len(row["value_to"]) > MAX_VALUE_LENGTH:
        raise ValueError(f"Each value must be at most {MAX_VALUE_LENGTH} characters.")
    value = row["value"].strip()
    upper = row["value_to"].strip()
    if not value:
        raise ValueError("Enter a value for this condition.")
    if operation != "between" and upper:
        raise ValueError("An upper value is only allowed for a numeric range.")

    condition = {"path": tuple(path), "operator": operation}
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


def _walk_fields(data, path, depth, seen):
    """
    Yield each usable leaf path once while bounding recursion

    Parameters
    ----------
    data : object
        Current JSON value.
    path : tuple of str
        Dictionary keys traversed so far.
    depth : int
        Current nesting depth, including arrays.
    seen : set
        Paths already yielded for this object.

    Yields
    ------
    tuple of str
        Unique selectable scalar paths.
    """
    if depth > MAX_DEPTH:
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if _searchable_key(key):
                yield from _walk_fields(value, path + (key,), depth + 1, seen)
    elif isinstance(data, list):
        for value in data:
            if path in seen and not isinstance(value, (dict, list)):
                continue
            yield from _walk_fields(value, path, depth + 1, seen)
    elif data is not None and path and path not in seen:
        if len(json.dumps(path, ensure_ascii=False, separators=(",", ":"))) <= MAX_PATH_LENGTH:
            seen.add(path)
            yield path


def discover_fields(data):
    """
    Discover scalar field paths in stored JSON

    Parameters
    ----------
    data : object
        Stored JSON value.

    Returns
    -------
    iterable of tuple
        Paths containing literal dictionary keys and no array indices.
    """
    return _walk_fields(data, (), 0, set())


def _field_values(data, path, depth=0):
    """
    Yield scalars at an exact path with transparent array traversal

    Parameters
    ----------
    data : object
        Current JSON value.
    path : tuple of str
        Remaining dictionary keys to traverse.
    depth : int, optional
        Current nesting depth, including arrays.

    Yields
    ------
    object
        Nonnull scalar candidates at the requested path only.
    """
    if depth > MAX_DEPTH:
        return
    if isinstance(data, list):
        for value in data:
            yield from _field_values(value, path, depth + 1)
    elif path:
        if isinstance(data, dict) and path[0] in data:
            yield from _field_values(data[path[0]], path[1:], depth + 1)
    elif data is not None and not isinstance(data, dict):
        yield data


def _matches_condition(data, condition):
    """
    Evaluate one prepared comparison against scalar candidates

    Parameters
    ----------
    data : object
        Stored JSON value.
    condition : dict
        Validated path, operator, and comparison values.

    Returns
    -------
    bool
        Whether the condition matches any appropriate scalar candidates.
    """
    operation = condition["operator"]
    expected = condition["value"]
    values = _field_values(data, condition["path"])
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


def format_field_path(path):
    """
    Format exact field keys as a readable path label

    Parameters
    ----------
    path : tuple of str
        Literal JSON dictionary keys.

    Returns
    -------
    str
        Human readable field label.
    """
    return " / ".join(path)
