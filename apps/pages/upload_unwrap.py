from django.conf import settings

from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS
from apps.dyn_api.metadata_compat import field_name


RECORD_FIELDS = frozenset(field_name(name) for name in REQUIRED_TOP_LEVEL_FIELDS) | {"identifier"}
SIMULATION_FIELDS = frozenset(field_name(name) for name in ("mechanical_BC", "phase", "stress", "total_strain", "RVE_size"))
WRAPPER_METADATA_FIELDS = RECORD_FIELDS | {"description", "$schema", "$id", "version"}


def object_paths(payload):
    """
    Locate records inside collections without splitting recognized record contents

    Incomplete and scalar collection members remain in the result so validation
    can reject them. Only paths are retained by the batch precheck.

    Parameters
    ----------
    payload : dict or list
        One parsed JSON file.

    Returns
    -------
    list of tuple
        Record locations in original document order.
    """
    paths = []
    pending = [(iter((((), payload),)), False)]
    while pending:
        children, collection_entry = pending[-1]
        try:
            path, value = next(children)
        except StopIteration:
            pending.pop()
            continue
        if len(path) >= settings.PILOT_MAX_JSON_DEPTH:
            paths.append(path)
        elif isinstance(value, list):
            if not value and collection_entry:
                paths.append(path)
            else:
                pending.append((iter(_children(value, path)), True))
        elif isinstance(value, dict):
            names = {field_name(key) for key in value}
            known = RECORD_FIELDS.intersection(names)
            if len(known) >= 3 or SIMULATION_FIELDS.intersection(names) or not value:
                paths.append(path)
            elif isinstance(value.get("data"), list):
                pending.append((iter(_children(value["data"], path + ("data",))), True))
            elif known and not any(_contains_record(child) for child in value.values()):
                paths.append(path)
            elif not any(isinstance(child, (dict, list)) for child in value.values()):
                paths.append(path)
            else:
                excluded = WRAPPER_METADATA_FIELDS if known else ()
                pending.append((iter(_children(value, path, excluded)), True))
        else:
            paths.append(path)
        if len(paths) > settings.PILOT_MAX_UPLOAD_OBJECTS:
            break
    return paths


def _children(value, path, excluded=()):
    """
    Traverse a container lazily without allocating a second wide work list

    Parameters
    ----------
    value : dict or list
        Collection to inspect.
    path : tuple
        Location of the collection.
    excluded : iterable of str, optional
        Descriptive wrapper keys that are not collection members.

    Yields
    ------
    tuple
        Child location and original value.
    """
    entries = value.items() if isinstance(value, dict) else enumerate(value)
    for key, child in entries:
        if not isinstance(key, str) or field_name(key) not in excluded:
            yield path + (key,), child


def _contains_record(value):
    """
    Detect a record below descriptive wrapper metadata without retaining its tree

    Parameters
    ----------
    value : object
        Potential collection value.

    Returns
    -------
    bool
        Whether a descendant has recognizable simulation fields.
    """
    pending = [iter((value,))]
    while pending:
        try:
            current = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        if isinstance(current, dict):
            names = {field_name(key) for key in current}
            if len(RECORD_FIELDS.intersection(names)) >= 3 or SIMULATION_FIELDS.intersection(names):
                return True
            children = current.values()
        elif isinstance(current, list):
            children = current
        else:
            continue
        if len(pending) < settings.PILOT_MAX_JSON_DEPTH:
            pending.append(iter(children))
    return False


def objects_at_paths(payload, paths):
    """
    Read the exact record boundaries established by the batch precheck

    Parameters
    ----------
    payload : dict or list
        Reopened JSON file.
    paths : list of tuple
        Inspected record paths.

    Returns
    -------
    list
        Original records, including invalid entries awaiting validation.
    """
    objects = []
    for path in paths:
        value = payload
        for key in path:
            value = value[key]
        objects.append(value)
    return objects
