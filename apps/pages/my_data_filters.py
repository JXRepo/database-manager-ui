from collections import Counter


FILTER_FIELDS = (
    ("access", "Access", ()),
    ("software", "Software", ("name", "software_name")),
    ("phase", "Phase", ("phase_name", "name", "phase_identifier", "identifier")),
    ("creator", "Creator", ("name", "creator_name", "author")),
)


def _metadata_names(value, name_keys):
    """
    Extract distinct text names from one metadata field

    Only explicit name keys contribute labels from dictionaries. Parameter
    values and numeric phase identifiers do not become dropdown choices.

    Parameters
    ----------
    value : object
        JSON field containing text, a list, or named objects.
    name_keys : tuple
        Recognized name keys in preferred order.

    Returns
    -------
    dict
        Names indexed by their trimmed, case insensitive values.
    """
    names = {}
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            label = item.strip()
            if label:
                names.setdefault(label.casefold(), label)
        elif isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, dict):
            for key in name_keys:
                name = item.get(key)
                if isinstance(name, str) and name.strip():
                    pending.append(name)
                    break
                if isinstance(name, list) and name:
                    pending.append(name)
                    break
    return names


def filter_my_data_objects(data_objects, query):
    """
    Filter owned objects and build dropdown choices with matching counts

    The caller supplies only the current user's objects. Each option counts
    records satisfying the other selected filters, counting each object once.

    Parameters
    ----------
    data_objects : iterable
        Owned JSONData objects in display order.
    query : QueryDict
        Selected dropdown values from the GET request.

    Returns
    -------
    dict
        Matching objects, dropdown definitions, and result totals.
    """
    selected = {}
    labels = {}
    counts = {}
    totals = Counter()
    for name, label, name_keys in FILTER_FIELDS:
        selected[name] = query.get(name, "").strip().casefold()
        labels[name] = {}
        counts[name] = Counter()
    labels["access"] = {"public": "Public", "private": "Private"}

    matches = []
    total_count = 0
    for obj in data_objects:
        total_count += 1
        data = obj.data if isinstance(obj.data, dict) else {}
        access = "public" if obj.access_type == "all" else "private"
        values = {"access": {access: labels["access"][access]}}
        for name, label, name_keys in FILTER_FIELDS[1:]:
            values[name] = _metadata_names(data.get(name), name_keys)

        mismatched = set()
        for name, names in values.items():
            for value, label in names.items():
                labels[name].setdefault(value, label)
            if selected[name] and selected[name] not in names:
                mismatched.add(name)

        if not mismatched:
            matches.append(obj)
        for name, names in values.items():
            if not mismatched or mismatched == {name}:
                totals[name] += 1
                counts[name].update(names.keys())

    filters = []
    for name, label, name_keys in FILTER_FIELDS:
        value = selected[name]
        if value and value not in labels[name]:
            labels[name][value] = query.get(name).strip()
        choices = labels[name].items()
        if name != "access":
            choices = sorted(choices)
        options = []
        for option_value, option_label in choices:
            options.append({
                "value": option_value,
                "label": option_label,
                "count": counts[name][option_value],
            })
        filters.append({
            "name": name, "label": label, "value": value,
            "options": options, "total": totals[name],
        })

    return {
        "data_objects": matches,
        "my_data_filters": filters,
        "total_count": total_count,
        "result_count": len(matches),
        "has_active_filters": any(selected.values()),
    }
