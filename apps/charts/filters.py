"""
Build visible filter choices from accessible statistical summaries
"""

from collections import Counter

from .analytics import CATEGORY_TITLES, COVERAGE_TITLES, MEASURES, RESULT_TITLES, distribution, in_bin, number


def checkbox_field(key, label, choices, selected, available_count, total_count, name=None):
    """
    Keep active conditions visible alongside available choices

    Retaining values absent from the scope lets users correct saved searches
    without silently dropping a condition when they submit the form.

    Parameters
    ----------
    key : str
        Stable field identifier.
    label : str
        Visible field label.
    choices : dict
        Available values with labels and distinct record counts.
    selected : list of str
        Current conditions for the field.
    available_count : int
        Scope records with at least one usable value.
    total_count : int
        Number of records in the data scope, before filtering.
    name : str, optional
        GET parameter name when different from the field identifier.

    Returns
    -------
    dict
        Checkbox options, selected summary and form parameter name.
    """
    options = {}
    for value, detail in choices.items():
        token = value.casefold() if key in CATEGORY_TITLES else value
        options.setdefault(token, {"value": value, **detail, "selected": False})
    for value in selected:
        token = value.casefold() if key in CATEGORY_TITLES else value
        option = options.setdefault(token, {"value": value, "label": value, "count": 0})
        option.update(value=value, selected=True)
    options = sorted(options.values(), key=lambda option: option["label"].casefold())
    for option in options:
        option.update(name=name or key, input_type="checkbox")
    labels = [option["label"] for option in options if option["selected"]]
    if len(labels) == 1:
        summary = labels[0]
    elif labels:
        summary = f"{len(labels)} selected"
    else:
        summary = "All"
    return {"key": key, "name": name or key, "label": label, "options": options,
            "summary": summary, "selected_count": len(labels),
            "available_count": available_count, "total_count": total_count}


def results_field(records, query):
    """
    Combine response coverage and output requirements in one menu

    Ordinary coverage choices are exclusive. Existing multiple or invalid
    conditions remain editable without losing their original AND meaning.

    Parameters
    ----------
    records : list of dict
        Statistical summaries in the complete accessible data scope.
    query : dict
        Current conditions, including bookmarked output requirements.

    Returns
    -------
    dict
        Grouped choices with counts and one combined selection summary.
    """
    total = len(records)
    selected = query.get("coverage", [])
    matching = sum(bool(record["curve_components"]) for record in records)
    exclusive = len(selected) <= 1 and all(value in COVERAGE_TITLES for value in selected)
    choices = {}
    if total or selected:
        if exclusive or "all" in selected:
            choices["all"] = {"label": "All", "count": total}
        choices["matching"] = {"label": "Available", "count": matching}
        choices["without_matching"] = {"label": "Not available", "count": total - matching}
    coverage = checkbox_field("coverage", "Results", choices, selected, total, total)
    for option in coverage["options"]:
        option.update(group="Matching stress–strain components", input_type="radio" if exclusive else "checkbox")
        option["is_all"] = exclusive and option["value"] == "all"
        if option["is_all"]:
            option["selected"] = not selected
        option["summary_label"] = {
            "matching": "Stress–strain available", "without_matching": "No matching stress–strain",
        }.get(option["value"], option["label"])
    counts = Counter()
    for record in records:
        counts.update(record["results"])
    selected_outputs = query.get("result", [])
    output_keys = {"stress", "total_strain", "plastic_strain"}
    choices = {}
    for key in (*sorted(output_keys), *selected_outputs):
        if counts[key] or key in selected_outputs:
            choices[key] = {"label": RESULT_TITLES.get(key, key), "count": counts[key]}
    outputs = checkbox_field("result", "Results", choices, selected_outputs, total, total)
    regular = []
    legacy = []
    for option in outputs["options"]:
        if option["value"] in output_keys:
            option["group"] = "Required outputs"
            regular.append(option)
        else:
            option["group"] = "Other active conditions"
            legacy.append(option)
    options = coverage["options"] + regular + legacy
    labels = [option.get("summary_label", option["label"]) for option in options
              if option["selected"] and not option.get("is_all")]
    summary = "All"
    if len(labels) == 1:
        summary = labels[0]
    elif labels:
        summary = f"{len(labels)} selected"
    return {"key": "results", "label": "Results", "options": options,
            "summary": summary, "selected_count": len(labels), "total_count": total,
            "coverage_label": "Any results in",
            "available_count": sum(bool(output_keys & record["results"]) for record in records)}


def build_filter_fields(records, query):
    """
    Offer category and numeric filters within the current data scope

    Choices use compact summaries from the whole scope so changing a condition
    remains possible after filtering the charts down to an empty selection.

    Parameters
    ----------
    records : list of dict
        Accessible summaries without retained raw JSON or curves.
    query : dict
        Validated GET parameters, including current conditions.

    Returns
    -------
    list of dict
        Primary fields followed by additional category and interval fields.
    """
    fields = []
    total = len(records)
    for key in ("phase", "software", "loading_type", "loading_mode", "texture", "elastic_model", "plastic_model"):
        labels = {}
        counts = Counter()
        available = 0
        for record in records:
            values = record["categories"][key]
            available += bool(values)
            for value in values:
                labels.setdefault(value.casefold(), value)
            counts.update({value.casefold() for value in values})
        choices = {label: {"label": label, "count": counts[token]} for token, label in labels.items()}
        if key in {"phase", "software"} or available or query.get(key):
            fields.append(checkbox_field(key, CATEGORY_TITLES[key], choices, query.get(key, []), available, total))
    fields.insert(2, results_field(records, query))
    for measure in ("temperature", "grain_count"):
        title, unit, _observations = MEASURES[measure]
        stats = distribution(records, measure)
        intervals = {}
        for bucket in stats["bins"]:
            value = ":".join([measure, bucket["low"], bucket["high"], "1" if bucket["inclusive"] else "0"])
            intervals[value] = {"label": bucket["label"], "count": bucket["object_count"]}
        selected = [value for value in query.get("range", []) if value.partition(":")[0] == measure]
        for value in selected:
            parts = value.split(":")
            caption = "Invalid interval"
            count = 0
            low = number(parts[1]) if len(parts) == 4 else None
            high = number(parts[2]) if len(parts) == 4 else None
            if low is not None and high is not None and 0 <= low <= high and parts[3] in {"0", "1"}:
                caption = parts[1]
                if low != high:
                    upper_bound = f"< {parts[2]}" if parts[3] == "0" else parts[2]
                    caption = f"{parts[1]} – {upper_bound}"
                count = sum(any(in_bin(item, low, high, parts[3] == "1") for item in record["numeric"][measure])
                            for record in records)
            intervals.setdefault(value, {"label": caption, "count": count})
        label = f"{title} ({unit})" if unit else title
        if stats["object_count"] or selected:
            fields.append(checkbox_field(f"{measure}_range", label, intervals, selected,
                                         stats["object_count"], total, name="range"))
    return fields
