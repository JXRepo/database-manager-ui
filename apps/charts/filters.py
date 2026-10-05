"""
Build visible filter choices from accessible statistical summaries
"""

from .analytics import CATEGORY_TITLES, COVERAGE_TITLES, MEASURES, NOTE_DETAILS, RESULT_TITLES, distribution, number


def checkbox_field(key, label, choices, selected, name=None):
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
        Available values and their labels.
    selected : list of str
        Current conditions for the field.
    name : str, optional
        GET parameter name when different from the field identifier.

    Returns
    -------
    dict
        Checkbox options, selected summary and form parameter name.
    """
    options = {}
    for value, title in choices.items():
        token = value.casefold() if key in CATEGORY_TITLES else value
        options.setdefault(token, {"value": value, "label": title, "selected": False})
    for value in selected:
        token = value.casefold() if key in CATEGORY_TITLES else value
        option = options.setdefault(token, {"value": value, "label": value})
        option.update(value=value, selected=True)
    options = sorted(options.values(), key=lambda option: option["label"].casefold())
    labels = [option["label"] for option in options if option["selected"]]
    if len(labels) == 1:
        summary = labels[0]
    elif labels:
        summary = f"{len(labels)} selected"
    else:
        summary = "All"
    return {"key": key, "name": name or key, "label": label, "options": options,
            "summary": summary, "selected_count": len(labels)}


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
    choices = {key: {} for key in CATEGORY_TITLES}
    for record in records:
        for key, labels in record["categories"].items():
            for label in labels:
                choices[key].setdefault(label, label)
    choices["coverage"] = COVERAGE_TITLES
    choices["result"] = {key: title for key, title in RESULT_TITLES.items()
                         if key != "paired" or key in query.get("result", [])}
    choices["note"] = {key: title for key, (title, _description) in NOTE_DETAILS.items()}
    titles = {**CATEGORY_TITLES, "coverage": "Stress–strain coverage", "result": "Reported outputs",
              "note": "Statistics notes"}
    fields = []
    for key in ("phase", "software", "coverage", "texture", "elastic_model", "plastic_model",
                "loading_type", "loading_mode", "result"):
        fields.append(checkbox_field(key, titles[key], choices[key], query.get(key, [])))
    for measure, (title, unit, _observations) in MEASURES.items():
        intervals = {}
        for bucket in distribution(records, measure)["bins"]:
            value = ":".join([measure, bucket["low"], bucket["high"], "1" if bucket["inclusive"] else "0"])
            intervals[value] = bucket["label"]
        selected = [value for value in query.get("range", []) if value.partition(":")[0] == measure]
        for value in selected:
            parts = value.split(":")
            caption = "Invalid interval"
            if len(parts) == 4 and number(parts[1]) is not None and number(parts[2]) is not None:
                caption = parts[1]
                if number(parts[1]) != number(parts[2]):
                    upper_bound = f"< {parts[2]}" if parts[3] == "0" else parts[2]
                    caption = f"{parts[1]} – {upper_bound}"
            intervals.setdefault(value, caption)
        label = f"{title} ({unit})" if unit else title
        fields.append(checkbox_field(f"{measure}_range", label, intervals, selected, name="range"))
    fields.append(checkbox_field("note", titles["note"], choices["note"], query.get("note", [])))
    return fields
