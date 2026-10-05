"""
Prepare labelled SVG charts from statistical counts and distributions
"""

import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext

from .analytics import format_number


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
        SVG columns, boundary labels, count ticks and unchanged interval links.
    """
    bins = distribution["bins"]
    scale = axis_scale([bucket["count"] for bucket in bins], counts=True)
    slot = 574 / max(len(bins), 1)
    columns = []
    for index, bucket in enumerate(bins):
        height = float(Decimal(bucket["count"]) / scale["maximum"]) * 146
        width = min(slot * .66, 108) if distribution["constant"] else slot - 1
        center = 62 + slot * (index + .5)
        columns.append({**bucket, "x": round(center - width / 2, 2), "center": round(center, 2),
                        "y": round(174 - height, 2), "width": round(width, 2),
                        "plot_height": round(height, 2), "count_y": round(167 - height, 2),
                        "low_label": bucket["display_low"], "high_label": bucket["display_high"]})
    x_ticks = []
    if bins:
        if distribution["constant"]:
            x_ticks.append({"label": bins[0]["display_low"], "x": columns[0]["center"], "anchor": "middle"})
        else:
            longest = max(len(bucket[key]) for bucket in bins for key in ("display_low", "display_high"))
            divisions = 2 if longest > 8 else 4
            indices = sorted({round(index * len(bins) / divisions) for index in range(divisions + 1)})
            for index in indices:
                label = bins[index]["display_low"] if index < len(bins) else bins[-1]["display_high"]
                anchor = "start" if index == 0 else "end" if index == len(bins) else "middle"
                x_ticks.append({"label": label, "x": round(62 + slot * index, 2), "anchor": anchor})
    return {"columns": columns, "x_ticks": x_ticks,
            "ticks": [{**tick, "y": round(174 - tick["position"] * 146, 2)} for tick in scale["ticks"]]}


def pie_plot(rows):
    """
    Draw disjoint object coverage slices without altering their counts

    Parameters
    ----------
    rows : list of dict
        Exhaustive coverage categories with counts, colors and filter links.

    Returns
    -------
    dict
        SVG sector paths and full-circle metadata for the current selection.
    """
    total = sum(row["count"] for row in rows)
    center_x, center_y, radius = 130, 130, 96
    slices = []
    start = -math.pi / 2
    for row in rows:
        if not row["count"] or not total:
            continue
        angle = math.tau * row["count"] / total
        end = start + angle
        x_start, y_start = center_x + radius * math.cos(start), center_y + radius * math.sin(start)
        x_end, y_end = center_x + radius * math.cos(end), center_y + radius * math.sin(end)
        full_circle = row["count"] == total
        if full_circle:
            path = (f"M{center_x},{center_y - radius} "
                    f"A{radius},{radius} 0 1 1 {center_x},{center_y + radius} "
                    f"A{radius},{radius} 0 1 1 {center_x},{center_y - radius} Z")
        else:
            path = (f"M{center_x},{center_y} L{x_start:.3f},{y_start:.3f} "
                    f"A{radius},{radius} 0 {int(angle > math.pi)} 1 {x_end:.3f},{y_end:.3f} Z")
        slices.append({**row, "path": path, "full_circle": full_circle})
        start = end
    return {"slices": slices, "total": total, "center_x": center_x, "center_y": center_y, "radius": radius}
