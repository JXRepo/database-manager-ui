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
        Maximum rows drawn in the initial or expanded category chart.

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
                     "label_y": 34 + index * 42, "value_x": round(134 + width + 7, 2)})
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


def pie_plot(rows, inner_radius=0):
    """
    Draw disjoint object coverage slices without altering their counts

    Parameters
    ----------
    rows : list of dict
        Exhaustive coverage categories with counts, colors and filter links.
    inner_radius : int, optional
        Hole radius for a donut, or zero for a filled pie.

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
            if inner_radius:
                path += (f" M{center_x},{center_y - inner_radius} "
                         f"A{inner_radius},{inner_radius} 0 1 0 {center_x},{center_y + inner_radius} "
                         f"A{inner_radius},{inner_radius} 0 1 0 {center_x},{center_y - inner_radius} Z")
        elif inner_radius:
            inner_start_x = center_x + inner_radius * math.cos(start)
            inner_start_y = center_y + inner_radius * math.sin(start)
            inner_end_x = center_x + inner_radius * math.cos(end)
            inner_end_y = center_y + inner_radius * math.sin(end)
            path = (f"M{x_start:.3f},{y_start:.3f} "
                    f"A{radius},{radius} 0 {int(angle > math.pi)} 1 {x_end:.3f},{y_end:.3f} "
                    f"L{inner_end_x:.3f},{inner_end_y:.3f} "
                    f"A{inner_radius},{inner_radius} 0 {int(angle > math.pi)} 0 {inner_start_x:.3f},{inner_start_y:.3f} Z")
        else:
            path = (f"M{center_x},{center_y} L{x_start:.3f},{y_start:.3f} "
                    f"A{radius},{radius} 0 {int(angle > math.pi)} 1 {x_end:.3f},{y_end:.3f} Z")
        slices.append({**row, "path": path, "full_circle": full_circle})
        start = end
    return {"slices": slices, "total": total, "center_x": center_x, "center_y": center_y,
            "radius": radius, "inner_radius": inner_radius}


def bubble_plot(rows, limit=6):
    """
    Show independent category counts with proportional circle areas

    A fixed grid keeps labels legible without suggesting disjoint proportions.

    Parameters
    ----------
    rows : list of dict
        Category counts and filter links.
    limit : int, optional
        Categories shown initially, with all others available in the table.

    Returns
    -------
    dict
        Circle geometry with an exact count for each category.
    """
    shown = rows[:limit]
    maximum = max((row["count"] for row in shown), default=1)
    colors = ("#347bb5", "#31877c", "#7968aa", "#b87d35", "#4b899c", "#a85f7f")
    circles = []
    for index, row in enumerate(shown):
        radius = 43 * math.sqrt(row["count"] / maximum)
        y = 56 + (index // 3) * 120
        row_length = min(3, len(shown) - (index // 3) * 3)
        circles.append({**row, "x": 180 + ((index % 3) - (row_length - 1) / 2) * 118, "y": y, "radius": radius,
                        "color": colors[index % len(colors)], "count_y": y + 4 if radius >= 15 else y + 25,
                        "inside": radius >= 15, "label_y": y + 46,
                        "label_x": 126 + ((index % 3) - (row_length - 1) / 2) * 118})
    return {"rows": circles, "maximum": maximum, "height": 280 if len(shown) > 3 else 160}


def column_plot(rows, limit=6):
    """
    Draw software counts on a common vertical axis starting at zero

    Full category names remain in link titles and the expanded category chart.

    Parameters
    ----------
    rows : list of dict
        Category counts and filter links.
    limit : int, optional
        Maximum visible columns.

    Returns
    -------
    dict
        Columns and integer count ticks for an SVG chart.
    """
    shown = rows[:limit]
    scale = axis_scale([row["count"] for row in shown], counts=True)
    slot = 340 / max(len(shown), 1)
    columns = []
    for index, row in enumerate(shown):
        height = float(Decimal(row["count"]) / scale["maximum"]) * 150
        center = 48 + slot * (index + .5)
        columns.append({**row, "x": round(center - min(slot * .6, 64) / 2, 2), "center": round(center, 2),
                        "width": round(min(slot * .6, 64), 2), "height": round(height, 2),
                        "y": round(192 - height, 2), "count_y": round(184 - height, 2),
                        "label_x": round(48 + index * slot + 2, 2), "label_width": round(slot - 4, 2)})
    return {"rows": columns, "ticks": [{**tick, "y": round(192 - tick["position"] * 150, 2)}
                                        for tick in scale["ticks"]]}


def heatmap_plot(matrix, limit=6):
    """
    Color observed loading combinations by their distinct object counts

    Empty cells remain visible and have no navigation link. Full combinations
    are retained in the HTML table when the visible axes are limited.

    Parameters
    ----------
    matrix : dict
        Counts and URLs for object level loading type and mode combinations.
    limit : int, optional
        Maximum categories on each visible axis.

    Returns
    -------
    dict
        Bounded cells, shortened axis labels and a visible count scale.
    """
    types, modes = matrix["types"][:limit], matrix["modes"][:min(limit, 4)]
    counts = {(row["type"].casefold(), row["mode"].casefold()): row for row in matrix["pairs"]}
    maximum = max((row["count"] for row in matrix["pairs"]), default=1)
    width, height = 252 / max(len(modes), 1), 168 / max(len(types), 1)
    cells = []
    for y_index, type_row in enumerate(types):
        for x_index, mode_row in enumerate(modes):
            row = counts.get((type_row["label"].casefold(), mode_row["label"].casefold()), {})
            count = row.get("count", 0)
            strength = count / maximum
            color = "#f1f5f8" if not count else "#{:02x}{:02x}{:02x}".format(
                round(226 - strength * 185), round(237 - strength * 113), round(246 - strength * 79))
            cells.append({**row, "type": type_row["label"], "mode": mode_row["label"], "count": count,
                          "x": round(116 + x_index * width, 2), "y": round(48 + y_index * height, 2),
                          "width": round(width - 3, 2), "height": round(height - 3, 2), "color": color,
                          "center_x": round(116 + (x_index + .5) * width - 1.5, 2),
                          "center_y": round(48 + (y_index + .5) * height - 1.5, 2), "dark": strength > .55})
    return {
        "cells": cells, "maximum": maximum,
        "types": [{"label": row["label"], "y": round(38 + (index + .5) * height - 1.5, 2)}
                  for index, row in enumerate(types)],
        "modes": [{"label": row["label"], "x": round(116 + index * width, 2), "width": round(width - 3, 2)}
                  for index, row in enumerate(modes)],
    }


def box_plot(distribution):
    """
    Plot exact quartiles with whiskers at the supplied minimum and maximum

    Decimal normalization preserves nearby large grain counts. Quartiles use
    linear interpolation at fractions of the ordered observation positions.

    Parameters
    ----------
    distribution : dict
        Numeric summary containing a five value box and its interval link.

    Returns
    -------
    dict
        Box geometry, readable ticks and an unchanged numeric selection.
    """
    box = distribution.get("box")
    if not box:
        return {}
    values = box["values"]
    scale = axis_scale(values)
    with localcontext() as context:
        context.prec = scale["precision"]
        positions = [float((value - scale["minimum"]) / (scale["maximum"] - scale["minimum"])) * 300 + 40
                     for value in values]
    low, q1, median, q3, high = positions
    ticks = scale["ticks"]
    if max(len(tick["label"]) for tick in ticks) > 5 and len(ticks) > 3:
        ticks = [ticks[index] for index in sorted({0, (len(ticks) - 1) // 2, len(ticks) - 1})]
    return {**box, "minimum_x": low, "q1_x": q1, "median_x": median, "q3_x": q3, "maximum_x": high,
            "width": q3 - q1, "constant": values[0] == values[-1], "offset": scale["offset"],
            "ticks": [{**tick, "x": round(40 + tick["position"] * 300, 2),
                       "anchor": "start" if index == 0 else "end" if index == len(ticks) - 1 else "middle"}
                      for index, tick in enumerate(ticks)]}
