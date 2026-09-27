"""
Apply MiMeDat required fields and conditional requirements using local schemas

This is a required field profile, not a claim of full JSON Schema compliance.
Other numeric, enum and optional field constraints remain outside this profile.
"""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft201909Validator, ValidationError, validators


SCHEMA_DIRECTORY = Path(__file__).with_name("schemas")
SCHEMA_REFERENCES = {
    "https://raw.githubusercontent.com/Ronakshoghi/MetadataSchema/main/general_constitutive_model_metadata_schema.json": "constitutive.json",
    "https://raw.githubusercontent.com/YousefRezek/MicrostructureEvolutionDataSchema/main/Microstructure_Module.json": "microstructure.json",
}


def is_empty(value):
    """
    Recognize empty field values without treating zero or false as empty

    Parameters
    ----------
    value : object
        Supplied field value.

    Returns
    -------
    bool
        Whether the value is null, blank text or an empty container.
    """
    return value is None or (isinstance(value, str) and not value.strip()) or (
        isinstance(value, (list, dict)) and not value
    )


def _profile(schema):
    """
    Retain required paths and the structures needed to reach them

    References resolve exclusively through the bundled allowlist. Conditions
    retain their original predicates; unrelated optional constraints are omitted.

    Parameters
    ----------
    schema : dict
        Trusted schema fragment.

    Returns
    -------
    dict
        Required field validation profile.
    """
    if "$ref" in schema:
        filename = SCHEMA_REFERENCES[schema["$ref"]]
        schema = json.loads((SCHEMA_DIRECTORY / filename).read_text())
    result = {}
    if schema.get("required"):
        result["required"] = schema["required"]
    properties = {}
    for name, child in schema.get("properties", {}).items():
        child_profile = _profile(child)
        if child_profile:
            properties[name] = child_profile
    if properties:
        result["properties"] = properties
    if isinstance(schema.get("items"), dict):
        items = _profile(schema["items"])
        if items:
            result["items"] = items
    for keyword in ("allOf", "oneOf", "anyOf"):
        branches = [_profile(child) for child in schema.get(keyword, [])]
        if any(branches):
            if keyword != "allOf":
                for branch, original in zip(branches, schema[keyword]):
                    if "type" in original:
                        branch["type"] = original["type"]
            result[keyword] = branches
    if "if" in schema:
        then = _profile(schema.get("then", {}))
        otherwise = _profile(schema.get("else", {}))
        if then or otherwise:
            result.update({"if": schema["if"], "then": then, "else": otherwise})
    if result and "type" in schema:
        result["type"] = schema["type"]
    return result


def _required(validator, fields, instance, schema):
    """
    Report missing fields and empty required values separately

    Parameters
    ----------
    validator : Validator
        Current schema validator.
    fields : list of str
        Fields required at this location.
    instance : object
        Uploaded value.
    schema : dict
        Current validation fragment.

    Yields
    ------
    ValidationError
        One issue with the affected child path.
    """
    if not isinstance(instance, dict):
        return
    for field in fields:
        if field not in instance:
            yield ValidationError("Required field is missing.", validator="missing_required", path=[field])
        elif is_empty(instance[field]):
            yield ValidationError("Required field is empty.", validator="empty_values", path=[field])


def _properties(validator, properties, instance, schema):
    """
    Inspect supplied nonempty containers without rejecting optional blanks

    Parameters
    ----------
    validator : Validator
        Current schema validator.
    properties : dict
        Known child profiles.
    instance : object
        Uploaded value.
    schema : dict
        Current validation fragment.

    Yields
    ------
    ValidationError
        Nested field issues.
    """
    if isinstance(instance, dict):
        for field, child in properties.items():
            if field in instance and not is_empty(instance[field]):
                yield from validator.descend(instance[field], child, path=field, schema_path=field)


def _conditional(validator, condition, instance, schema):
    """
    Activate a conditional requirement only when its controlling fields exist

    Parameters
    ----------
    validator : Validator
        Current schema validator.
    condition : dict
        Original JSON Schema predicate.
    instance : object
        Uploaded value.
    schema : dict
        Fragment containing the conditional branches.

    Yields
    ------
    ValidationError
        Issues from the applicable branch.
    """
    supplied = isinstance(instance, dict) and all(
        field in instance and not is_empty(instance[field]) for field in condition.get("properties", {})
    )
    branch = "then" if supplied and Draft201909Validator(condition).is_valid(instance) else "else"
    yield from validator.descend(instance, schema.get(branch, {}), schema_path=branch)


def _one_of(validator, branches, instance, schema):
    """
    Keep missing tensor components visible instead of a generic alternative error

    Parameters
    ----------
    validator : Validator
        Current schema validator.
    branches : list of dict
        Scalar or container alternatives.
    instance : object
        Uploaded value.
    schema : dict
        Current validation fragment.

    Yields
    ------
    ValidationError
        Specific issues from the matching structural alternative.
    """
    matches = [branch for branch in branches
               if Draft201909Validator({"type": branch["type"]}).is_valid(instance)]
    if len(matches) == 1:
        yield from validator.descend(instance, matches[0])
    else:
        yield from Draft201909Validator.VALIDATORS["oneOf"](validator, branches, instance, schema)


@lru_cache(maxsize=1)
def _validator():
    """
    Compile the bundled nested requirements once per application process

    Returns
    -------
    Validator
        Offline validator for nested required fields.
    """
    source = json.loads((SCHEMA_DIRECTORY / "mechanical.json").read_text())
    profile = _profile(source)
    profile.pop("required")
    validator_type = validators.extend(Draft201909Validator, {
        "required": _required, "properties": _properties, "if": _conditional, "oneOf": _one_of,
    })
    return validator_type(profile)


def field_path(path):
    """
    Format a path using field names and one based list positions

    Parameters
    ----------
    path : iterable of str or int
        Location in the uploaded object.

    Returns
    -------
    str
        Readable location such as phase[1].phase_name.
    """
    result = ""
    for part in path:
        if isinstance(part, int):
            result += f"[{part + 1}]"
        else:
            result += ("." if result else "") + part
    return result


def nested_required_issues(data):
    """
    Group all nested requirement failures without editing uploaded values

    Parameters
    ----------
    data : dict
        One data object.

    Returns
    -------
    dict
        Issue categories mapped to affected field paths, with concise structure
        messages that never include the uploaded value.
    """
    issues = {}
    for error in _validator().iter_errors(data):
        category = error.validator if error.validator in {"missing_required", "empty_values"} else "invalid_structure"
        path = field_path(error.absolute_path)
        fields = issues.setdefault(category, [])
        if path not in fields:
            fields.append(path)
        if category == "invalid_structure":
            expected = error.validator_value if error.validator == "type" else "a number or a tensor object"
            if isinstance(expected, list):
                expected = " or ".join(expected)
            issues.setdefault("structure_messages", []).append(f"{path}: expected {expected}.")
    return issues
