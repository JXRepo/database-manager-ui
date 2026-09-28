"""
Recognize harmless metadata formatting differences without editing uploaded JSON
"""

import hashlib
import json
import math
import re
from functools import lru_cache

from .required_schema import SCHEMA_DIRECTORY, SCHEMA_REFERENCES, field_path, is_empty


NUMBER_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
FIELD_NAME_ALIASES = {"cpuspecifications": "processorspecifications"}


def field_name(value):
    """
    Compare field names independently of formatting and explicit supported aliases

    Parameters
    ----------
    value : str
        Uploaded or schema field name.

    Returns
    -------
    str
        Comparable name, retaining the reserved dollar prefix.
    """
    prefix = "$" if value.startswith("$") else ""
    name = prefix + re.sub(r"[\W_]+", "", value.casefold())
    return FIELD_NAME_ALIASES.get(name, name)


def unwrap_single_value(value):
    """
    Remove singleton list wrappers where the caller expects one value

    Parameters
    ----------
    value : object
        Value at a known scalar or object location.

    Returns
    -------
    object
        Innermost value, stopping at any empty or multiple item list.
    """
    while isinstance(value, list) and len(value) == 1:
        value = value[0]
    return value


def field_value(data, name, default=None):
    """
    Read one field without normalizing a record's potentially large arrays

    Parameters
    ----------
    data : object
        Metadata dictionary.
    name : str
        Expected field name.
    default : object, optional
        Value returned for a missing field.

    Returns
    -------
    object
        Matched value with singleton wrappers removed for known non-array fields.
        Other values and genuine arrays retain their original structure.
    """
    if not isinstance(data, dict):
        return default
    if name in data:
        value = data[name]
    else:
        expected = field_name(name)
        for key, value in data.items():
            if field_name(key) == expected:
                break
        else:
            return default
    root = _metadata_shape()
    shape = root["properties"].get(root["names"].get(field_name(name)))
    return unwrap_single_value(value) if shape and shape["single_value"] else value


def set_field_value(data, name, value):
    """
    Set a generated value while retaining its field spelling and singleton wrappers

    Parameters
    ----------
    data : dict
        Mutable uploaded data object.
    name : str
        Expected field name.
    value : object
        Replacement value.
    """
    keys = [key for key in data if field_name(key) == field_name(name)]
    for key in keys or [name]:
        original = data.get(key)
        replacement = value
        while isinstance(original, list) and len(original) == 1:
            replacement = [replacement]
            original = original[0]
        data[key] = replacement


def identifier_lookup(value):
    """
    Build a bounded database lookup key without changing identifier text

    Parameters
    ----------
    value : object
        Supplied or generated identifier.

    Returns
    -------
    str
        Digest for a nonempty text identifier, otherwise an empty string.
    """
    if not isinstance(value, str) or not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _shape(schema):
    """
    Compile names and value hints from a trusted schema fragment

    Parameters
    ----------
    schema : dict
        Bundled schema or reference to a bundled schema.

    Returns
    -------
    dict
        Recognition hints without validation or network operations.
    """
    if "$ref" in schema:
        schema = json.loads((SCHEMA_DIRECTORY / SCHEMA_REFERENCES[schema["$ref"]]).read_text())
    properties = dict(schema.get("properties", {}))
    types = schema.get("type", [])
    types = {types} if isinstance(types, str) else set(types)
    for branch in schema.get("oneOf", []):
        properties.update(branch.get("properties", {}))
        if "type" in branch:
            types.add(branch["type"])
    children = {name: _shape(child) for name, child in properties.items()}
    return {
        "names": {field_name(name): name for name in children},
        "properties": children,
        "items": _shape(schema["items"]) if isinstance(schema.get("items"), dict) else None,
        "single_value": bool(types) and "array" not in types,
        "numeric": bool(types.intersection({"number", "integer"})),
        "enum": {value.casefold(): value for value in schema.get("enum", []) if isinstance(value, str)},
    }


@lru_cache(maxsize=1)
def _metadata_shape():
    """
    Load recognition hints once for the platform's trusted metadata schema

    Returns
    -------
    dict
        Root hints, including platform sharing usernames and document headers.
    """
    schema = json.loads((SCHEMA_DIRECTORY / "mechanical.json").read_text())
    for name in ("$schema", "$id", "version", "type"):
        schema["properties"][name] = {}
    schema["properties"]["shared_with"]["items"]["properties"]["username"] = {"type": "string"}
    return _shape(schema)


def _sharing_entry(value):
    """
    Interpret explicit sharing shorthand without searching arbitrary text

    Parameters
    ----------
    value : object
        One sharing entry.

    Returns
    -------
    object
        Equivalent permission object or the original unrecognized entry.
    """
    value = unwrap_single_value(value)
    if isinstance(value, str) and value.strip().casefold() in {"all", "c"}:
        return {"access_type": value.strip().casefold()}
    if isinstance(value, dict):
        names = {field_name(key): key for key in value}
        if "accesstype" not in names:
            if "username" in names:
                return dict(value, access_type="c")
            if len(value) == 1:
                name, original = next(iter(names.items()))
                if name in {"all", "c"} and unwrap_single_value(value[original]) is True:
                    return {"access_type": name}
    return value


def _recognized(value, shape, path, conflicts):
    """
    Build a recognized view while retaining unknown fields and source containers

    Parameters
    ----------
    value : object
        Uploaded value.
    shape : dict
        Recognition hints for this schema path.
    path : tuple
        Canonical path used for conflict feedback.
    conflicts : list
        Receives pairs of disagreeing original field paths.

    Returns
    -------
    object
        Recognized value, sharing unchanged containers when possible.
    """
    if shape["single_value"]:
        value = unwrap_single_value(value)
    if path == ("shared_with",) and not is_empty(value):
        entries = value if isinstance(value, list) else [value]
        value = [_sharing_entry(entry) for entry in entries]
    if isinstance(value, dict):
        result = {}
        originals = {}
        for key, child in value.items():
            name = shape["names"].get(field_name(key), key)
            child_shape = shape["properties"].get(name)
            recognized = _recognized(child, child_shape, path + (name,), conflicts) if child_shape else child
            if name in result:
                first = json.dumps(result[name], sort_keys=True, ensure_ascii=True)
                second = json.dumps(recognized, sort_keys=True, ensure_ascii=True)
                if first != second:
                    conflicts.append((field_path(path + (originals[name],)), field_path(path + (key,))))
            else:
                result[name] = recognized
                originals[name] = key
        return result
    if isinstance(value, list) and shape["items"]:
        result = [_recognized(child, shape["items"], path + (index,), conflicts)
                  for index, child in enumerate(value)]
        return value if all(first is second for first, second in zip(value, result)) else result
    if isinstance(value, str):
        text = value.strip()
        if shape["numeric"] and NUMBER_TEXT.fullmatch(text):
            try:
                number = float(text) if any(char in text for char in ".eE") else int(text)
                if isinstance(number, int) or math.isfinite(number):
                    return number
            except ValueError:
                pass
        if text.casefold() in shape["enum"]:
            return shape["enum"][text.casefold()]
    return value


def metadata_view(data, conflicts=None):
    """
    Recognize schema fields and numeric text without modifying stored metadata

    Parameters
    ----------
    data : object
        Raw data object.
    conflicts : list, optional
        Receives conflicting aliases for upload feedback.

    Returns
    -------
    dict
        Canonical lookup view used by validation, search and visualization.
    """
    if not isinstance(data, dict):
        return {}
    return _recognized(data, _metadata_shape(), (), conflicts if conflicts is not None else [])
