"""
Compare bounded recorded metadata while keeping original simulation data untouched
"""

import csv
from decimal import Decimal, InvalidOperation
import hashlib
from io import StringIO
import json
import math
import re

from django.db.models import Q
from django.urls import reverse

from apps.dyn_api.metadata_compat import NUMBER_TEXT, field_name, unwrap_single_value
from apps.charts.analytics import COMPONENTS, curve_summary


SUMMARY_VERSION = 2
MAX_COMPARISON_OBJECTS = 4
MAX_FIELD_ENTRIES = 8
MAX_VALUE_CHARACTERS = 240
MAX_PROJECTION_BYTES = 32 * 1024
_AMBIGUOUS_VALUE = object()
COMPARISON_FIELDS = (
    ("software", "Software", "Simulation setup"),
    ("software_version", "Software version", "Simulation setup"),
    ("phase", "Phase entries", "Material and microstructure"),
    ("texture", "Texture", "Material and microstructure"),
    ("lattice_structure", "Crystal structure", "Material and microstructure"),
    ("grain_count", "Grain number", "Material and microstructure"),
    ("elastic_model", "Elastic model", "Material and microstructure"),
    ("plastic_model", "Plastic model", "Material and microstructure"),
    ("rve_size", "RVE dimensions", "Discretization and boundaries"),
    ("rve_continuity", "RVE continuity", "Discretization and boundaries"),
    ("discretization_type", "Discretization type", "Discretization and boundaries"),
    ("discretization_count", "Discretization count", "Discretization and boundaries"),
    ("temperature", "Global temperature", "Loading and units"),
    ("loading", "Loading conditions", "Loading and units"),
    ("units", "Recorded units", "Loading and units"),
    ("outputs", "Mechanical output availability", "Mechanical outputs"),
)
STATE_LABELS = {
    "recorded": "Recorded", "not_supplied": "Not supplied",
    "ambiguous": "Ambiguous", "truncated": "Preview only",
}
PHASE_FIELDS = {
    "phase": ("phase_name",), "texture": ("orientation", "texture_type"),
    "lattice_structure": ("lattice_structure",), "grain_count": ("orientation", "grain_count"),
    "elastic_model": ("constitutive_model", "elastic_model_name"),
    "plastic_model": ("constitutive_model", "plastic_model_name"),
}
UNIT_FIELDS = ("Length", "Temperature", "Stress", "Strain", "Time", "Force", "Angle", "Frequency")


def outdated_summary_query():
    """
    Find missing or obsolete projections with explicit JSON missing-key handling

    Returns
    -------
    Q
        Portable SQLite and PostgreSQL predicate for summaries needing preparation.
    """
    return (Q(collection_summary__isnull=True)
            | Q(collection_summary__summary_version__isnull=True)
            | Q(collection_summary__summary_version=None)
            | ~Q(collection_summary__summary_version=SUMMARY_VERSION))


def _interpret(value, kind):
    """
    Describe only known scalar shapes without copying arbitrary containers

    Parameters
    ----------
    value : object
        A recognized field value or a value paired with its explicit unit.
    kind : str
        Expected scalar, text, numeric, boolean, vector or quantity shape.

    Returns
    -------
    tuple
        Display text, typed equality value and completeness state.
    """
    if kind.startswith("quantity_"):
        amount, unit = value
        display, token, state = _interpret(amount, kind.removeprefix("quantity_"))
        if state != "recorded":
            return display, token, state
        if not isinstance(unit, str) or not unit.strip():
            return display + " (unit not supplied)", None, "not_supplied"
        return display + " " + unit, [token, ["unit", unit]], "recorded"
    if value is None or value == "" or value == [] or value == {}:
        return "Not supplied", None, "not_supplied"
    if kind in {"number", "boolean", "scalar"}:
        value = unwrap_single_value(value)
        if value is None or value == "" or value == [] or value == {}:
            return "Not supplied", None, "not_supplied"
    if kind == "number" and isinstance(value, str) and NUMBER_TEXT.fullmatch(value.strip()):
        try:
            if Decimal(value.strip()).is_finite():
                return value, ["numeric_text", value], "recorded"
        except InvalidOperation:
            return "Unsupported numeric value", None, "ambiguous"
    if isinstance(value, str):
        if not value.strip():
            return "Not supplied", None, "not_supplied"
        if kind not in {"text", "scalar"}:
            return "Unsupported value", None, "ambiguous"
        return value, ["text", value], "recorded"
    if isinstance(value, bool):
        if kind not in {"boolean", "scalar"}:
            return "Unsupported value", None, "ambiguous"
        return json.dumps(value), ["boolean", value], "recorded"
    if isinstance(value, (int, float)) and kind in {"number", "scalar"}:
        if isinstance(value, float) and not math.isfinite(value):
            return "Non-finite value", None, "ambiguous"
        return str(value), [type(value).__name__, value], "recorded"
    if isinstance(value, list) and kind in {"text", "scalar", "vector"}:
        displays, tokens, states = [], [], []
        for item in value[:MAX_FIELD_ENTRIES]:
            display, token, state = _interpret(item, "number" if kind == "vector" else "scalar")
            if kind == "text" and not isinstance(item, str):
                state = "ambiguous"
            displays.append(display)
            tokens.append(token)
            states.append(state)
        state = "recorded"
        if any(item != "recorded" for item in states):
            state = "ambiguous" if "ambiguous" in states else "not_supplied"
        if len(value) > MAX_FIELD_ENTRIES:
            state = "truncated"
        display = "[" + ", ".join(displays) + "]" if kind == "vector" else "; ".join(displays)
        return display, ["list", tokens], state
    return "Unsupported value", None, "ambiguous"


def _cell(entries, conflicts=(), *, truncated=False):
    """
    Bound one field and retain conservative completeness and equality information

    Parameters
    ----------
    entries : list of tuple
        Context, canonical path, supplied value and expected shape.
    conflicts : sequence of str, optional
        Normalized conflicting source field paths.
    truncated : bool, optional
        Whether additional parent entries were intentionally omitted.

    Returns
    -------
    dict
        Bounded display entries and a hash available only for complete recorded values.
    """
    result = {"state": "recorded", "entries": [], "key": "", "truncated": truncated}
    tokens, states = [], []
    for context, path, value, kind in entries[:MAX_FIELD_ENTRIES]:
        related = [field_name(part) for part in path.split(" + ")]
        if any(candidate.startswith(conflict) for candidate in related for conflict in conflicts):
            display, token, state = "Conflicting field names", None, "ambiguous"
        else:
            display, token, state = _interpret(value, kind)
        if len(display) > MAX_VALUE_CHARACTERS:
            display = display[:MAX_VALUE_CHARACTERS - 1] + "…"
            state = "truncated"
        result["entries"].append({"context": context, "path": path, "value": display, "state": state})
        tokens.append([path, token])
        states.append(state)
    result["truncated"] = truncated or len(entries) > MAX_FIELD_ENTRIES or "truncated" in states
    if "ambiguous" in states:
        result["state"] = "ambiguous"
    elif result["truncated"]:
        result["state"] = "truncated"
    elif not entries or "not_supplied" in states:
        result["state"] = "not_supplied"
    if result["state"] == "recorded":
        serialized = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        result["key"] = hashlib.sha256(serialized.encode()).hexdigest()
    return result


def _output_entries(data):
    """
    Keep each mechanical series count beside its own component and supplied unit

    Parameters
    ----------
    data : dict
        Canonical metadata view with original curve arrays retained only transiently.

    Returns
    -------
    list of tuple
        One bounded textual availability entry per supplied mechanical group.
    """
    entries = []
    units = data.get("units")
    units = units if isinstance(units, dict) else {}
    for name, prefix, equivalent, unit_name in (
        ("stress", "stress", "equivalent_stress", "Stress"),
        ("total_strain", "strain", "equivalent_strain", "Strain"),
        ("plastic_strain", "plastic_strain", "equivalent_plastic_strain", "Strain"),
    ):
        group = data.get(name)
        if not isinstance(group, dict):
            continue
        series = []
        counts = {}
        for key in [f"{prefix}_{component}" for component in COMPONENTS] + [equivalent]:
            values = group.get(key)
            try:
                valid = isinstance(values, list) and bool(values) and all(
                    isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                    for value in values
                )
            except OverflowError:
                valid = False
            if valid:
                counts[key] = len(values)
                series.append(f"{key}: {len(values)} samples")
        if equivalent not in group and all(f"{prefix}_{component}" in counts for component in COMPONENTS):
            count = min(counts[f"{prefix}_{component}"] for component in COMPONENTS)
            series.append(f"{equivalent}: calculated, {count} samples")
        if series:
            unit = units.get(unit_name)
            unit_display = str(unit) if isinstance(unit, str) or (unit_name == "Strain" and type(unit) in (int, float) and unit == 1) else "not supplied"
            entries.append((name, name + " + units." + unit_name, "; ".join(series) + "; unit: " + unit_display, "text"))
    return entries


def _recorded_field(parent, name):
    """
    Read original numeric spelling without losing precision in the compatibility view

    Parameters
    ----------
    parent : object
        The original object at this known schema parent.
    name : str
        Exact schema field name, ignoring case and separator punctuation only.

    Returns
    -------
    object
        Original value, no supplied value, or a conflicting-shape sentinel.
    """
    parent = unwrap_single_value(parent)
    if parent is _AMBIGUOUS_VALUE:
        return _AMBIGUOUS_VALUE
    if not isinstance(parent, dict):
        return None
    values = [value for key, value in parent.items() if field_name(key) == field_name(name)]
    if len(values) > 1 and len({json.dumps(unwrap_single_value(value), sort_keys=True) for value in values}) > 1:
        return _AMBIGUOUS_VALUE
    return values[0] if values else None


def _comparison_conflict_path(path):
    """
    Translate validation positions to the comparison's zero-based schema locators

    Parameters
    ----------
    path : str
        Compatibility conflict path with one-based array positions.

    Returns
    -------
    str
        Normalized field path with zero-based positions for exact parent matching.
    """
    zero_based = re.sub(r"\[([1-9][0-9]*)\]", lambda match: f"[{int(match[1]) - 1}]", path)
    return field_name(zero_based)


def build_study_projection(data, conflicts=(), *, original=None):
    """
    Extract a bounded simulation setup projection from the compatibility view

    Phase indices and loading-condition indices remain separate. Equality concerns
    recorded values only; this function never establishes physical comparability.

    Parameters
    ----------
    data : dict
        Recognized metadata without changes to the original record.
    conflicts : sequence of tuple, optional
        Conflicting original field paths reported by the compatibility view.
    original : dict or None, optional
        Original record used transiently to retain exact numeric text and supplied types.

    Returns
    -------
    dict
        Versioned scalar fields and availability information without curve arrays.
    """
    conflict_paths = [_comparison_conflict_path(path) for pair in conflicts for path in pair]
    fields = {}
    original = data if original is None else original
    units = data.get("units")
    units = units if isinstance(units, dict) else {}
    original_units = _recorded_field(original, "units")
    for key, path, kind in (
        ("software", "software", "text"), ("software_version", "software_version", "scalar"),
        ("rve_continuity", "RVE_continuity", "boolean"),
        ("discretization_type", "discretization_type", "text"),
        ("discretization_count", "discretization_count", "number"),
    ):
        value = _recorded_field(original, path) if kind == "number" else data.get(path)
        fields[key] = _cell([("", path, value, kind)], conflict_paths)
    for key, path, kind, unit in (
        ("rve_size", "RVE_size", "quantity_vector", "Length"),
        ("temperature", "global_temperature", "quantity_number", "Temperature"),
    ):
        value = _recorded_field(original, path)
        unit_value = unwrap_single_value(_recorded_field(original_units, unit))
        fields[key] = _cell([("", path + " + units." + unit, (value, unit_value), kind)], conflict_paths)
    phases = data.get("phase", [])
    phases = phases if isinstance(phases, list) else [phases]
    original_phases = _recorded_field(original, "phase")
    original_phase_conflict = original_phases is _AMBIGUOUS_VALUE
    original_phases = original_phases if isinstance(original_phases, list) else [original_phases]
    for key, path in PHASE_FIELDS.items():
        entries = []
        for index, phase in enumerate(phases[:MAX_FIELD_ENTRIES]):
            current = phase
            for part in path[:-1]:
                current = current.get(part) if isinstance(current, dict) else None
            value = current.get(path[-1]) if isinstance(current, dict) else None
            if key == "grain_count" and isinstance(current, dict):
                original_phase = (_AMBIGUOUS_VALUE if original_phase_conflict else
                                  original_phases[index] if index < len(original_phases) else {})
                original_orientation = unwrap_single_value(_recorded_field(original_phase, "orientation"))
                if original_orientation is _AMBIGUOUS_VALUE:
                    entries.append((f"Phase {index + 1}", f"phase[{index}]." + ".".join(path),
                                    _AMBIGUOUS_VALUE, "number"))
                    continue
                original_orientation = original_orientation if isinstance(original_orientation, dict) else {}
                alternatives = [unwrap_single_value(item) for name, item in original_orientation.items()
                                if field_name(name) in {"graincount", "grainnumber"}]
                interpreted = [_interpret(item, "number") for item in alternatives]
                if len({json.dumps(item[1]) for item in interpreted}) > 1:
                    value = {"ambiguous": True}
                elif alternatives:
                    value = alternatives[0]
            entries.append((f"Phase {index + 1}", f"phase[{index}]." + ".".join(path), value,
                            "number" if key == "grain_count" else "text"))
        fields[key] = _cell(entries, conflict_paths, truncated=len(phases) > MAX_FIELD_ENTRIES)
    conditions = data.get("mechanical_BC", [])
    conditions = conditions if isinstance(conditions, list) else [conditions]
    entries = []
    for index, condition in enumerate(conditions[:MAX_FIELD_ENTRIES]):
        for name in ("loading_type", "loading_mode"):
            value = condition.get(name) if isinstance(condition, dict) else None
            entries.append((f"Condition {index + 1}", f"mechanical_BC[{index}].{name}", value, "text"))
    fields["loading"] = _cell(entries, conflict_paths, truncated=len(conditions) > MAX_FIELD_ENTRIES)
    fields["units"] = _cell([("", "units." + name, _recorded_field(original_units, name), "scalar")
                             for name in UNIT_FIELDS if name in units], conflict_paths)
    available, _, notes, components = curve_summary(data)
    fields["outputs"] = _cell(_output_entries(data), conflict_paths)
    output_conflict = any(
        field_name(path.split(".", 1)[0]) in {"stress", "totalstrain", "plasticstrain"}
        for pair in conflicts for path in pair
    )
    if output_conflict:
        fields["outputs"].update(state="ambiguous", entries=[], key="")
    elif "invalid_curves" in notes:
        fields["outputs"].update(state="ambiguous", key="")
    elif "result_units" in notes and fields["outputs"]["state"] == "recorded":
        fields["outputs"].update(state="not_supplied", key="")
    projection = {
        "version": 1, "fields": fields,
        "outputs": {"has_response": bool(components), "available": sorted(available), "notes": sorted(notes)},
    }
    while len(json.dumps(projection, ensure_ascii=False).encode()) > MAX_PROJECTION_BYTES:
        largest = max(fields.values(), key=lambda cell: len(json.dumps(cell, ensure_ascii=False).encode()))
        if not largest["entries"]:
            break
        largest["entries"].pop()
        largest.update(state="truncated", key="", truncated=True)
    return projection


def parse_comparison_ids(params):
    """
    Accept one ordered canonical selection of at most four object identifiers

    Parameters
    ----------
    params : QueryDict or dict
        Workspace GET arguments.

    Returns
    -------
    list of int
        Distinct object identifiers preserving the reference object first.

    Raises
    ------
    ValueError
        Selection arguments are repeated, malformed, duplicate or too long.
    """
    values = params.getlist("compare") if hasattr(params, "getlist") else [params.get("compare", "")]
    if not values:
        return []
    if len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 79:
        raise ValueError("Choose up to four distinct data objects for comparison.")
    if values[0] == "":
        return []
    tokens = values[0].split(",")
    if len(tokens) > MAX_COMPARISON_OBJECTS or any(not re.fullmatch(r"[1-9][0-9]{0,18}", value) for value in tokens):
        raise ValueError("Choose up to four distinct data objects for comparison.")
    ids = [int(value) for value in tokens]
    if len(set(ids)) != len(ids) or any(value > 9223372036854775807 for value in ids):
        raise ValueError("Choose up to four distinct data objects for comparison.")
    return ids


def build_comparison_context(accessible_queryset, params, *, base_url):
    """
    Prepare complete comparison rows only after checking every selected member

    Parameters
    ----------
    accessible_queryset : QuerySet
        Currently accessible members of the current collection or selection.
    params : QueryDict or dict
        Ordered comparison IDs and optional differences flag.
    base_url : str
        Canonical workspace URL for recovery and continuation.

    Returns
    -------
    dict
        Bounded table, selected objects or explicit preparation and validation state.
    """
    from .collection_graph import CollectionSummaryPending, collection_summaries

    context = {
        "ids": [], "objects": [], "rows": [], "counts": {"same": 0, "different": 0, "incomplete": 0},
        "error": "", "ready": False, "preparation": None, "differences": False,
        "selection_value": "", "base_url": base_url,
    }
    try:
        ids = parse_comparison_ids(params)
        differences = params.getlist("differences") if hasattr(params, "getlist") else [params.get("differences", "0")]
        if len(differences) > 1 or (differences and differences[0] not in {"0", "1"}):
            raise ValueError("Choose a valid difference display.")
        context.update(ids=ids, selection_value=",".join(map(str, ids)), differences=differences == ["1"])
        selected = accessible_queryset.filter(pk__in=ids)
        if selected.count() != len(ids):
            raise ValueError("Some comparison objects are unavailable. Choose accessible objects from this collection again.")
        if not ids:
            return context
        summaries = list(collection_summaries(selected, require_comparison=len(ids) >= 2))
        by_id = {row["pk"]: row for row in summaries}
        if set(by_id) != set(ids):
            raise ValueError("Some comparison objects are unavailable. Choose accessible objects from this collection again.")
        context["objects"] = [by_id[pk] for pk in ids]
        for index, obj in enumerate(context["objects"]):
            obj["is_reference"] = index == 0
        if len(ids) < 2:
            return context
        for key, label, group in COMPARISON_FIELDS:
            cells = []
            for obj in context["objects"]:
                cell = dict(obj["comparison"]["fields"][key])
                cell.update(object_pk=obj["pk"], state_label=STATE_LABELS[cell["state"]])
                cells.append(cell)
            complete = all(cell["state"] == "recorded" for cell in cells)
            status = "incomplete" if not complete else "same" if len({cell["key"] for cell in cells}) == 1 else "different"
            for index, cell in enumerate(cells):
                cell["matches_reference"] = (cell["key"] == cells[0]["key"]
                                              if index and cell["state"] == cells[0]["state"] == "recorded" else None)
            context["rows"].append({"key": key, "label": label, "group": group, "cells": cells, "status": status})
            context["counts"][status] += 1
        context["ready"] = True
    except CollectionSummaryPending as exc:
        context["preparation"] = {"ready_count": exc.ready_count, "total_count": exc.total_count,
                                  "requires_admin": exc.requires_admin}
        cached = dict(selected.values_list("pk", "collection_summary"))
        if set(cached) != set(ids):
            context.update(ids=[], objects=[], rows=[], preparation=None, selection_value="",
                           error="Some comparison objects are unavailable. Choose accessible objects from this collection again.")
            return context
        context["objects"] = []
        for index, pk in enumerate(ids):
            summary = cached[pk] or {}
            detail_url = reverse("json_data_detail", args=[pk])
            context["objects"].append({"pk": pk, "title": summary.get("title", ""),
                                       "identifier": summary.get("identifier", ""), "detail_url": detail_url,
                                       "graph_url": detail_url + "?tab=graph", "is_reference": index == 0})
    except ValueError as exc:
        context.update(ids=[], objects=[], rows=[], error=str(exc), selection_value="")
    return context


def comparison_csv(context):
    """
    Export an explicit metadata snapshot with states and schema locators

    Parameters
    ----------
    context : dict
        Ready comparison whose entire selection has passed current access checks.

    Returns
    -------
    str
        CSV text with spreadsheet formula protection and bounded-preview scope.
    """
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(("field", "comparison_status", "object_id", "identifier", "title", "state", "context", "path", "value", "entry_state", "scope"))
    for row in context["rows"]:
        if context["differences"] and row["status"] == "same":
            continue
        for obj, cell in zip(context["objects"], row["cells"]):
            entries = cell["entries"] or [{"context": "", "path": "", "value": STATE_LABELS[cell["state"]]}]
            for entry in entries:
                values = [row["label"], row["status"], str(obj["pk"]), obj["identifier"], obj["title"],
                          cell["state"], entry["context"], entry["path"], entry["value"], entry.get("state", cell["state"]),
                          f"Recorded metadata snapshot: at most {MAX_FIELD_ENTRIES} entries per field and {MAX_VALUE_CHARACTERS} characters per value; schema locators; original JSON unchanged; no physical comparability claim"]
                safe = []
                for value in values:
                    text = str(value)
                    safe.append("'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text)
                writer.writerow(safe)
    return output.getvalue()
