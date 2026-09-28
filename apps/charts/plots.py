"""
Prepare labelled SVG charts from the existing statistical and curve values
"""

import math
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_FLOOR, localcontext

from apps.dyn_api.metadata_compat import metadata_view
from apps.pages.views import _extract_plot_variables
from .analytics import COMPONENTS, format_number, number


def axis_scale(values, counts=False):
    """
    Produce readable tick marks without changing the plotted source values

    Parameters
    ----------
    values : iterable
        Finite numeric observations.
    counts : bool, optional
        Start at zero and use integer ticks for object counts.

    Returns
    -------
    dict
        Decimal bounds, display offset and ticks with normalized positions.
    """
    values = [Decimal(str(value)) for value in values]
    low, high = min(values, default=Decimal(0)), max(values, default=Decimal(1))
    with localcontext() as context:
        context.prec = max(40, high.adjusted() - min(low.as_tuple().exponent, high.as_tuple().exponent) + 12,
                           len(low.as_tuple().digits) + 12, len(high.as_tuple().digits) + 12)
        if counts:
            low, high = Decimal(0), max(high, Decimal(1))
        elif low == high:
            padding = abs(low) / 10 or Decimal(1)
            low, high = low - padding, high + padding
        raw_step = (high - low) / 5
        magnitude = Decimal(10) ** raw_step.adjusted()
        step = next(Decimal(factor) * magnitude for factor in (1, 2, 5, 10)
                    if Decimal(factor) * magnitude >= raw_step)
        if counts:
            step = max(step, Decimal(1))
        start = (low / step).to_integral_value(rounding=ROUND_FLOOR) * step
        end = (high / step).to_integral_value(rounding=ROUND_CEILING) * step
        offset = Decimal(0)
        if not counts and abs(start) > (end - start) * 10000:
            offset_step = Decimal(10) ** ((end - start).adjusted() + 1)
            offset = (start / offset_step).to_integral_value(rounding=ROUND_FLOOR) * offset_step
        offset_label = f"{'+' if offset > 0 else ''}{format_number(offset, context.prec)}" if offset else ""
        ticks = []
        for index in range(int((end - start) / step) + 1):
            value = start + index * step
            ticks.append({"label": format_number(value - offset, 10), "position": float((value - start) / (end - start))})
    return {"minimum": start, "maximum": end, "ticks": ticks, "offset": offset_label,
            "precision": context.prec}


def bar_plot(rows, limit=6):
    """
    Position category counts on one labelled count axis

    Parameters
    ----------
    rows : list of dict
        Labels, counts and links for the current object selection.
    limit : int, optional
        Initial rows drawn, with remaining rows retained for the data table.

    Returns
    -------
    dict
        SVG geometry and all rows for accessible category navigation.
    """
    shown = rows[:limit]
    scale = axis_scale([row["count"] for row in shown], counts=True)
    baseline = 26 + max(len(shown), 1) * 42
    bars = []
    for index, row in enumerate(shown):
        width = float(Decimal(row["count"]) / scale["maximum"]) * 172
        bars.append({**row, "width": round(width, 2), "y": 19 + index * 42,
                     "label_y": 34 + index * 42, "value_x": round(134 + width + 7, 2),
                     "short_label": row["label"] if len(row["label"]) <= 19 else row["label"][:17] + "…"})
    return {"rows": bars, "all_rows": rows, "height": baseline + 43, "baseline": baseline,
            "ticks": [{**tick, "x": round(134 + tick["position"] * 172, 2)} for tick in scale["ticks"]]}


def histogram_plot(distribution):
    """
    Draw every numeric bin including a real column for singleton data

    Parameters
    ----------
    distribution : dict
        Exact bins and observation units from the statistical summary.

    Returns
    -------
    dict
        SVG columns, count ticks and unchanged interval links.
    """
    bins = distribution["bins"]
    scale = axis_scale([bucket["count"] for bucket in bins], counts=True)
    slot = 574 / max(len(bins), 1)
    columns = []
    for index, bucket in enumerate(bins):
        low_label, _separator, high_label = bucket["label"].partition(" – ")
        height = float(Decimal(bucket["count"]) / scale["maximum"]) * 146
        width = min(slot * .66, 108)
        center = 62 + slot * (index + .5)
        columns.append({**bucket, "x": round(center - width / 2, 2), "center": round(center, 2),
                        "y": round(174 - height, 2), "width": round(width, 2),
                        "plot_height": round(height, 2), "count_y": round(167 - height, 2),
                        "low_label": low_label, "high_label": high_label.removeprefix("< ")})
    return {"columns": columns, "ticks": [{**tick, "y": round(174 - tick["position"] * 146, 2)}
                                          for tick in scale["ticks"]]}


def preview_indices(x_values, y_values, limit=2400):
    """
    Bound display size while retaining extrema and original sample traversal

    Parameters
    ----------
    x_values, y_values : list
        Numeric arrays paired by their original index.
    limit : int, optional
        Maximum displayed points; exports keep the original arrays.

    Returns
    -------
    list of int
        Increasing sample indices including both endpoints and bucket extrema.
    """
    count = min(len(x_values), len(y_values))
    if count <= limit:
        return list(range(count))
    size = math.ceil(count / ((limit - 2) // 4))
    indices = {0, count - 1}
    for start in range(0, count, size):
        bucket = range(start, min(start + size, count))
        for values in (x_values, y_values):
            indices.add(min(bucket, key=values.__getitem__))
            indices.add(max(bucket, key=values.__getitem__))
    return sorted(indices)


def curve_preview(data, component=""):
    """
    Plot one object's matching tensor or equivalent stress and strain pair

    Equivalent calculations use the detail page's existing rules. Original
    order, unequal lengths and the supplied or calculated origin stay explicit.

    Parameters
    ----------
    data : dict
        One accessible object's uploaded JSON.
    component : str, optional
        Requested tensor component or equivalent; blank chooses an available pair.

    Returns
    -------
    tuple
        Optional SVG curve description and available component choices.
    """
    conflicts = []
    metadata = metadata_view(data, conflicts)
    if conflicts or not isinstance(metadata, dict):
        return None, []
    units = metadata.get("units")
    units = units if isinstance(units, dict) else {}
    recognized = {}
    for group_name, prefix, equivalent in (("stress", "stress", "equivalent_stress"),
                                            ("total_strain", "strain", "equivalent_strain")):
        group = metadata.get(group_name)
        if not isinstance(group, dict):
            continue
        recognized[group_name] = {}
        for key in [*(f"{prefix}_{suffix}" for suffix in COMPONENTS), equivalent]:
            if key not in group:
                continue
            values = group[key]
            valid = isinstance(values, list) and values and all(
                isinstance(value, (int, float)) and not isinstance(value, bool) and number(value) is not None
                for value in values)
            recognized[group_name][key] = values if valid else []
    try:
        variables = _extract_plot_variables(recognized, units=units)
    except (OverflowError, ValueError):
        for group, equivalent in (("stress", "equivalent_stress"), ("total_strain", "equivalent_strain")):
            if group in recognized:
                recognized[group].setdefault(equivalent, [])
        variables = _extract_plot_variables(recognized, units=units)
    variables = {variable["key"]: variable for variable in variables
                 if all(number(value) is not None for value in variable["values"])}
    pairs = {}
    for suffix in ("equivalent", *COMPONENTS):
        x_key = "total_strain.equivalent_strain" if suffix == "equivalent" else f"total_strain.strain_{suffix}"
        y_key = "stress.equivalent_stress" if suffix == "equivalent" else f"stress.stress_{suffix}"
        if x_key in variables and y_key in variables:
            pairs[suffix] = (variables[x_key], variables[y_key])
    choices = [(key, "Equivalent" if key == "equivalent" else f"Component {key}") for key in pairs]
    selected = component or next(iter(pairs), "")
    if selected not in pairs:
        return None, choices
    x_variable, y_variable = pairs[selected]
    x_values, y_values = x_variable["values"], y_variable["values"]
    count = min(len(x_values), len(y_values))
    indices = preview_indices(x_values, y_values)
    points = []
    try:
        x_scale = axis_scale(x_values[index] for index in indices)
        y_scale = axis_scale(y_values[index] for index in indices)
        with localcontext() as context:
            context.prec = max(x_scale["precision"], y_scale["precision"])
            for index in indices:
                x_value, y_value = x_values[index], y_values[index]
                px = 74 + float((Decimal(str(x_value)) - x_scale["minimum"]) /
                                (x_scale["maximum"] - x_scale["minimum"])) * 622
                py = 248 - float((Decimal(str(y_value)) - y_scale["minimum"]) /
                                 (y_scale["maximum"] - y_scale["minimum"])) * 220
                points.append({"x": x_value, "y": y_value, "x_text": str(x_value), "y_text": str(y_value),
                               "px": round(px, 3), "py": round(py, 3), "index": index})
    except (DecimalException, OverflowError, ValueError):
        return None, choices
    strain_unit = units.get("Strain")
    stress_unit = units.get("Stress")
    x_unit = "−" if not isinstance(strain_unit, bool) and strain_unit in (1, "1") else strain_unit
    x_unit = x_unit.strip() if isinstance(x_unit, str) and x_unit.strip() else "unit not supplied"
    y_unit = stress_unit.strip() if isinstance(stress_unit, str) and stress_unit.strip() else "unit not supplied"
    x_name = "Equivalent strain" if selected == "equivalent" else f"Strain ε{selected.translate(str.maketrans('123', '₁₂₃'))}"
    y_name = "Equivalent stress" if selected == "equivalent" else f"Stress σ{selected.translate(str.maketrans('123', '₁₂₃'))}"
    return {
        "component": selected, "points": points, "count": count, "shown_count": len(points),
        "x_count": len(x_values), "y_count": len(y_values),
        "calculated": bool(x_variable.get("calculated") or y_variable.get("calculated")),
        "x_label": f"{x_name} ({x_unit})", "y_label": f"{y_name} ({y_unit})",
        "x_offset": x_scale["offset"], "y_offset": y_scale["offset"],
        "x_key": x_variable["key"], "y_key": y_variable["key"],
        "path": " ".join(f"{'M' if index == 0 else 'L'}{point['px']},{point['py']}" for index, point in enumerate(points)),
        "x_ticks": [{**tick, "x": round(74 + tick["position"] * 622, 3)} for tick in x_scale["ticks"]],
        "y_ticks": [{**tick, "y": round(248 - tick["position"] * 220, 3)} for tick in y_scale["ticks"]],
    }, choices
