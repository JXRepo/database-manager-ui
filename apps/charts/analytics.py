"""
Summarize accessible simulations without retaining their raw curves
"""

import math
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

from apps.dyn_api.metadata_compat import field_name, field_value, metadata_view, unwrap_single_value
from apps.pages.advanced_search import _temperature_in_kelvin

CATEGORY_TITLES = {
    "phase": "Phase", "software": "Software", "plastic_model": "Plastic model",
    "elastic_model": "Elastic model", "loading_type": "Loading type",
    "loading_mode": "Loading mode", "texture": "Texture",
}
MEASURES = {
    "temperature": ("Temperature", "K", "objects"),
    "grain_count": ("Grain number", "", "phases"),
    "discretization_count": ("Discretization count", "", "objects"),
}
RESULT_TITLES = {
    "stress": "Stress", "total_strain": "Total strain", "plastic_strain": "Plastic strain",
    "supplied_equivalent": "Supplied equivalent results",
    "calculated_equivalent": "Calculated equivalent results",
    "paired": "Stress and total strain",
    "matching_response": "Matching stress–strain components",
}
COVERAGE_TITLES = {
    "matching": "With matching stress–strain components",
    "without_matching": "Without matching stress–strain components",
}
NOTE_DETAILS = {
    "unequal_lengths": ("Different curve lengths", "The available series contain different numbers of points. Check the selected series on the detail page before comparing results."),
    "result_units": ("Result units not supplied", "At least one available stress or strain group has no usable unit declaration. Its arrays are still available on the detail page."),
    "temperature_excluded": ("Temperature not charted", "Temperature is missing, nonnumeric, below absolute zero, or has an unknown or missing unit. Other metadata remains available."),
    "invalid_curves": ("Unreadable curve values", "At least one supplied mechanical array contains nonnumeric, non-finite or boolean values. Empty arrays are treated as not supplied."),
    "conflicting_metadata": ("Conflicting metadata names", "Alternative names supply conflicting functional values. This object's metadata is excluded from statistics until the conflict is resolved; the original object remains accessible."),
    "grain_conflicts": ("Conflicting grain counts", "A phase supplies different values under alternative grain-count names. That phase is excluded from the grain distribution; its other metadata remains available."),
}
COMPONENTS = ("11", "22", "33", "12", "13", "23")


def text_values(value):
    """
    Collect distinct nonempty text without choosing between descriptions

    Parameters
    ----------
    value : object
        A recognized description or list of descriptions.

    Returns
    -------
    list of str
        Labels deduplicated by case and surrounding whitespace.
    """
    pending = [value]
    labels = {}
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, str) and item.strip():
            label = item.strip()
            labels.setdefault(label.casefold(), label)
    return list(labels.values())


def dictionaries(value):
    """
    Read dictionaries at a known schema collection location

    Parameters
    ----------
    value : object
        A single object or an object collection.

    Returns
    -------
    list of dict
        Supplied dictionaries without searching other parents.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def number(value, integer=False):
    """
    Read a finite scalar while excluding booleans and invalid counts

    Parameters
    ----------
    value : object
        Numeric metadata or a numeric string.
    integer : bool, optional
        Require a nonnegative integer count.

    Returns
    -------
    Decimal or None
        A value suitable for descriptive statistics.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value).strip())
        if not result.is_finite() or not math.isfinite(float(result)):
            return None
        if integer and (result < 0 or result != result.to_integral_value()):
            return None
        return result
    except (ValueError, InvalidOperation, OverflowError):
        return None


def format_number(value, precision=6):
    """
    Format a statistical value compactly without changing its numeric source

    Parameters
    ----------
    value : Decimal or None
        Value for display.
    precision : int, optional
        Significant digits used when a compact number is needed.

    Returns
    -------
    str
        Readable number or an unavailable marker.
    """
    if value is None:
        return "Not available"
    if value == value.to_integral_value() and abs(value) < Decimal("1e12"):
        return f"{int(value):,}"
    with localcontext() as context:
        context.prec = max(context.prec, len(value.as_tuple().digits))
        return format(value.normalize(), f".{precision}g")


def curve_summary(data):
    """
    Describe available mechanical series using the detail page's field rules

    No curve values are copied into the summary. A calculated equivalent is
    available only when its field is absent and all six components exist.

    Parameters
    ----------
    data : dict
        Recognized metadata for one object.

    Returns
    -------
    tuple
        Availability flags, distinct series lengths, note keys and paired components.
    """
    available = set()
    lengths = set()
    notes = set()
    components = {}
    units = data.get("units")
    units = units if isinstance(units, dict) else {}
    definitions = (
        ("stress", "stress", "equivalent_stress", "Stress"),
        ("total_strain", "strain", "equivalent_strain", "Strain"),
        ("plastic_strain", "plastic_strain", "equivalent_plastic_strain", "Strain"),
    )
    for group_name, prefix, equivalent, unit_name in definitions:
        group = data.get(group_name)
        if not isinstance(group, dict):
            continue
        valid = set()
        for key in [f"{prefix}_{component}" for component in COMPONENTS] + [equivalent]:
            values = group.get(key)
            if values is None or values == []:
                continue
            if not isinstance(values, list) or not values or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or number(value) is None
                for value in values
            ):
                notes.add("invalid_curves")
                continue
            valid.add(key)
            lengths.add(len(values))
        if not valid:
            continue
        components[group_name] = {suffix for suffix in COMPONENTS if f"{prefix}_{suffix}" in valid}
        available.add(group_name)
        if equivalent in valid:
            available.add("supplied_equivalent")
            components[group_name].add("equivalent")
        if equivalent not in group and all(f"{prefix}_{component}" in valid for component in COMPONENTS):
            available.add("calculated_equivalent")
            components[group_name].add("equivalent")
        unit = units.get(unit_name)
        has_unit = isinstance(unit, str) and bool(unit.strip())
        if unit_name == "Strain" and not isinstance(unit, bool) and unit == 1:
            has_unit = True
        if not has_unit:
            notes.add("result_units")
    if "stress" in available and "total_strain" in available:
        available.add("paired")
    if len(lengths) > 1:
        notes.add("unequal_lengths")
    paired_components = components.get("stress", set()) & components.get("total_strain", set())
    if paired_components:
        available.add("matching_response")
    return available, lengths, notes, paired_components


def summarize_object(obj):
    """
    Build a compact statistical record through the shared compatibility view

    Conflicting functional aliases cannot choose a statistical value. The
    object remains in the accessible total with an explanatory data note.

    Parameters
    ----------
    obj : JSONData
        Accessible stored record.

    Returns
    -------
    dict
        Identity, labels, loading pairs, numeric observations and result availability.
    """
    conflicts = []
    data = metadata_view(obj.data, conflicts)
    title = " / ".join(text_values(data.get("title"))) or "Untitled object"
    identifier = data.get("identifier")
    identifier = identifier if isinstance(identifier, str) else ""
    if conflicts:
        data = {}
        identifier = ""
    categories = {key: [] for key in CATEGORY_TITLES}
    categories["software"] = text_values(data.get("software"))
    numeric = {key: [] for key in MEASURES}
    grain_conflicts = False
    phases = dictionaries(data.get("phase"))
    for phase in phases:
        phase_labels = []
        for key in ("phase_name", "phase_identifier", "material", "name", "title"):
            phase_labels = text_values(field_value(phase, key))
            if phase_labels:
                break
        categories["phase"].extend(phase_labels)
        model = phase.get("constitutive_model")
        if isinstance(model, dict):
            for kind in ("plastic", "elastic"):
                categories[f"{kind}_model"].extend(text_values(model.get(f"{kind}_model_name")))
        orientation = phase.get("orientation")
        if isinstance(orientation, dict):
            categories["texture"].extend(text_values(orientation.get("texture_type")))
            counts = {number(unwrap_single_value(value), integer=True)
                      for key, value in orientation.items() if field_name(key) in {"graincount", "grainnumber"}}
            if len(counts) > 1:
                grain_conflicts = True
            elif counts and None not in counts:
                numeric["grain_count"].append(counts.pop())
    if not phases:
        categories["phase"] = text_values(data.get("phase"))
    loading_pairs = {}
    for condition in dictionaries(data.get("mechanical_BC")):
        for key in ("loading_type", "loading_mode"):
            categories[key].extend(text_values(condition.get(key)))
        loading_type = condition.get("loading_type")
        loading_mode = condition.get("loading_mode")
        if not isinstance(loading_type, str) or not isinstance(loading_mode, str):
            continue
        loading_type, loading_mode = loading_type.strip(), loading_mode.strip()
        if loading_type and loading_mode:
            loading_pairs.setdefault((loading_type.casefold(), loading_mode.casefold()), (loading_type, loading_mode))
    categories = {key: text_values(values) for key, values in categories.items()}
    units = data.get("units")
    units = units if isinstance(units, dict) else {}
    temperature = _temperature_in_kelvin(data.get("global_temperature"), units.get("Temperature"))
    temperature = number(temperature)
    if temperature is not None:
        numeric["temperature"].append(temperature)
    cells = number(data.get("discretization_count"), integer=True)
    if cells is not None:
        numeric["discretization_count"].append(cells)
    available, lengths, notes, paired_components = curve_summary(data)
    if conflicts:
        notes = {"conflicting_metadata"}
    elif temperature is None:
        notes.add("temperature_excluded")
    if grain_conflicts:
        notes.add("grain_conflicts")
    points = "No numeric series"
    if lengths:
        points = f"{min(lengths):,} points" if len(lengths) == 1 else f"{min(lengths):,}–{max(lengths):,} points"
    result_label = ("Stress + strain" if "matching_response" in available else
                    "Both groups supplied" if "paired" in available else
                    "Results supplied" if available else "No mechanical results")
    return {
        "id": obj.pk, "title": title, "identifier": identifier or f"Object {obj.pk}",
        "categories": categories, "loading_pairs": list(loading_pairs.values()),
        "numeric": numeric, "results": available, "notes": notes,
        "curve_components": paired_components,
        "phase_label": " / ".join(categories["phase"]) or "Not supplied",
        "software_label": " / ".join(categories["software"]) or "Not supplied",
        "result_label": result_label, "points": points,
        "access": "Public" if obj.access_type == "all" else "Private",
    }


def category_rows(records, field):
    """
    Count a normalized label once per accessible object

    Parameters
    ----------
    records : list of dict
        Summaries in the active statistical scope.
    field : str
        Supported category key.

    Returns
    -------
    dict
        All category counts and their distinct-object denominator.
    """
    counts = Counter()
    labels = {}
    present = 0
    for record in records:
        values = record["categories"][field]
        present += bool(values)
        for value in values:
            key = value.casefold()
            labels.setdefault(key, value)
            counts[key] += 1
    rows = []
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        percent = round(count * 100 / len(records), 1) if records else 0
        rows.append({"label": labels[key], "count": count, "percent": percent})
    return {"key": field, "title": CATEGORY_TITLES[field], "rows": rows,
            "available": present, "missing": len(records) - present, "total": len(records)}


def in_bin(value, low, high, inclusive):
    """
    Apply the same interval definition to chart bars and their object lists

    Parameters
    ----------
    value : Decimal
        Observation to compare.
    low : Decimal
        Inclusive lower bound.
    high : Decimal
        Upper bound.
    inclusive : bool
        Whether to include the upper bound.

    Returns
    -------
    bool
        Whether the observation belongs to the interval.
    """
    return low <= value and (value <= high if inclusive else value < high)


def distribution(records, measure):
    """
    Describe numeric coverage with exact bins and explicit observation units

    Grain observations belong to supplied phase entries. Bin links deduplicate
    objects even when multiple phases contribute to the same interval. Quartiles
    interpolate linearly at positions (n - 1) times the requested fraction.

    Parameters
    ----------
    records : list of dict
        Summaries in the active scope.
    measure : str
        Supported numeric measure.

    Returns
    -------
    dict
        Counts, quartiles, range and at most eight inclusive or half-open bins.
    """
    title, unit, observation_unit = MEASURES[measure]
    observations = []
    for record in records:
        observations.extend((value, record["id"]) for value in record["numeric"][measure])
    values = sorted(value for value, _pk in observations)
    object_count = len({pk for _value, pk in observations})
    result = {
        "key": measure, "title": title, "unit": unit, "observation_unit": observation_unit,
        "observation_count": len(values), "object_count": object_count,
        "excluded_objects": len(records) - object_count, "bins": [], "constant": False, "offset": "",
        "minimum": "Not available", "maximum": "Not available", "median": "Not available",
    }
    if not values:
        return result
    middle = len(values) // 2
    calculation_precision = max(28, max(len(value.as_tuple().digits) for value in values) + 12,
                                values[-1].adjusted() - min(value.as_tuple().exponent for value in values) + 12)
    with localcontext() as context:
        context.prec = calculation_precision
        median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        quartiles = []
        for fraction in (Decimal("0.25"), Decimal("0.75")):
            position = (len(values) - 1) * fraction
            index = int(position)
            weight = position - index
            quartiles.append(values[index] + weight * (values[min(index + 1, len(values) - 1)] - values[index]))
    q1, q3 = quartiles
    unique = sorted(set(values))
    intervals = []
    if len(unique) == 1:
        result["constant"] = True
        intervals = [(unique[0], unique[0], True)]
    else:
        bin_count = min(8, len(unique))
        with localcontext() as context:
            context.prec = calculation_precision
            width = (values[-1] - values[0]) / bin_count
            boundaries = [values[0], *(values[0] + width * index for index in range(1, bin_count)), values[-1]]
        intervals = [(boundaries[index], boundaries[index + 1], index == bin_count - 1)
                     for index in range(bin_count)]
    endpoints = {value for low, high, _inclusive in intervals for value in (low, high)}
    precision = 6
    while len({format_number(value, precision) for value in endpoints}) < len(endpoints):
        precision += 3
    precision = max(precision, len(values[0].as_tuple().digits), len(values[-1].as_tuple().digits),
                    len(median.as_tuple().digits), len(q1.as_tuple().digits), len(q3.as_tuple().digits))
    offset = Decimal(0)
    with localcontext() as context:
        context.prec = calculation_precision
        span = values[-1] - values[0]
        if span and abs(values[0]) > span * 10000:
            offset_step = Decimal(10) ** (span.adjusted() + 1)
            offset = (values[0] / offset_step).to_integral_value(rounding=ROUND_FLOOR) * offset_step
        if offset:
            result["offset"] = f"{'+' if offset > 0 else ''}{format_number(offset, calculation_precision)}"
        display_endpoints = {value - offset for value in endpoints}
    display_precision = 6
    while len({format_number(value, display_precision) for value in display_endpoints}) < len(display_endpoints):
        display_precision += 3
    result.update(minimum=format_number(values[0], precision), maximum=format_number(values[-1], precision),
                  median=format_number(median, precision))
    middle_matches = [pk for value, pk in observations if in_bin(value, q1, q3, True)]
    result["box"] = {
        "values": [values[0], q1, median, q3, values[-1]],
        "q1": format_number(q1, precision), "q3": format_number(q3, precision),
        "low": str(q1), "high": str(q3), "inclusive": True,
        "count": len(middle_matches), "object_count": len(set(middle_matches)),
    }
    for low, high, inclusive in intervals:
        matches = [pk for value, pk in observations if in_bin(value, low, high, inclusive)]
        if low == high:
            label = format_number(low, precision)
        else:
            label = f"{format_number(low, precision)} – {'< ' if not inclusive else ''}{format_number(high, precision)}"
        with localcontext() as context:
            context.prec = calculation_precision
            display_low = format_number(low - offset, display_precision)
            display_high = format_number(high - offset, display_precision)
        result["bins"].append({
            "label": label, "count": len(matches), "object_count": len(set(matches)),
            "low": str(low), "high": str(high), "inclusive": inclusive,
            "display_low": display_low, "display_high": display_high,
        })
    maximum_count = max(item["count"] for item in result["bins"])
    for item in result["bins"]:
        item["height"] = round(item["count"] * 100 / maximum_count, 2) if maximum_count else 0
    return result


def loading_matrix(records):
    """
    Count loading combinations reported together in one boundary entry

    Each object contributes once per pair, even when several entries repeat it.
    Incomplete entries do not supply either axis label for this matrix.

    Parameters
    ----------
    records : list of dict
        Metadata summaries for the active selection.

    Returns
    -------
    dict
        Observed combinations, axis categories and their object denominator.
    """
    available = []
    counts = Counter()
    for record in records:
        pairs = record["loading_pairs"]
        if not pairs:
            continue
        counts.update({(loading_type.casefold(), loading_mode.casefold()) for loading_type, loading_mode in pairs})
        available.append({"categories": {
            "loading_type": text_values([loading_type for loading_type, _ in pairs]),
            "loading_mode": text_values([loading_mode for _, loading_mode in pairs]),
        }})
    types = category_rows(available, "loading_type")["rows"]
    modes = category_rows(available, "loading_mode")["rows"]
    type_labels = {row["label"].casefold(): row["label"] for row in types}
    mode_labels = {row["label"].casefold(): row["label"] for row in modes}
    pairs = [{"type": type_labels[type_key], "mode": mode_labels[mode_key], "count": count,
              "percent": round(count * 100 / len(records), 1)}
             for (type_key, mode_key), count in counts.items()]
    pairs.sort(key=lambda row: (-row["count"], row["type"].casefold(), row["mode"].casefold()))
    return {"types": types, "modes": modes, "pairs": pairs, "available": len(available),
            "missing": len(records) - len(available)}
