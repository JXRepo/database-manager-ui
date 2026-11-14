"""
Inspect bounded original model and loading values in authorized study records
"""

from dataclasses import dataclass, field
import json
import math

from django.db import connections, transaction
from django.db.models import BigIntegerField, BinaryField, F, Func, TextField
from django.db.models.functions import Cast
from django.http import Http404
from django.urls import reverse

from apps.dyn_api.metadata_compat import DESCRIPTIVE_FIELDS, _metadata_shape, matched_field_name

from .research_collections import _owned_collection, _selection_ids, _validate_access, accessible_objects


MAX_PARAMETER_BYTES = 16 * 1024 * 1024
MAX_PARAMETER_ROWS = 300
MAX_VISITED_NODES = 6000
MAX_PARAMETER_DEPTH = 30
MAX_ARRAY_ENTRIES = 32
MAX_DISPLAY_CHARACTERS = 512
UNAVAILABLE_PARAMETERS = "Some selected objects are unavailable. Choose accessible records from this workspace again."
PARAMETER_LIMIT_MESSAGE = "These records exceed the detailed parameter limit of 16 MiB. Choose fewer or smaller records, or open their individual source pages."
SCOPE_NOTE = (
    "Recorded model settings, loading conditions and units only. Phase, condition and array positions "
    "are compared as supplied; names do not align phases. Units are shown separately without mapping "
    "or conversion. Matching rows do not establish scientific equivalence."
)
STATE_LABELS = {
    "recorded": "Recorded", "not_supplied": "Not supplied",
    "ambiguous": "Conflicting values", "truncated": "Preview only",
}
STATUS_LABELS = {"same": "Same recorded value", "different": "Different recorded values", "incomplete": "Incomplete information"}
_MISSING = object()


@dataclass
class InspectionBudget:
    """
    Track work and known omissions across every selected record
    """

    visited: int = 0
    limits: dict = field(default_factory=lambda: {
        "omitted_rows": 0, "omitted_array_entries": 0, "depth_limits": 0,
        "node_limits": 0, "shortened_values": 0,
    })

    def enter(self, depth):
        """
        Admit one source value only within both traversal allowances

        Parameters
        ----------
        depth : int
            Current nesting level, including accepted wrappers.

        Returns
        -------
        bool
            Whether this value can be inspected completely.
        """
        if depth > MAX_PARAMETER_DEPTH:
            self.limits["depth_limits"] += 1
            return False
        if self.visited >= MAX_VISITED_NODES:
            self.limits["node_limits"] += 1
            return False
        self.visited += 1
        return True


def _path(parent, key):
    """
    Preserve exact freeform names without confusing them with structural paths

    Parameters
    ----------
    parent : str
        Existing canonical or original source locator.
    key : str or int
        Object member name or array index.

    Returns
    -------
    str
        Unambiguous locator retaining array positions and original spelling.
    """
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if key.isidentifier():
        return f"{parent}.{key}" if parent else key
    return parent + "[" + json.dumps(key, ensure_ascii=False) + "]"


def _node(value=_MISSING, *, state="recorded", sources=(), kind="scalar", children=None):
    """
    Create one bounded intermediate source node

    Parameters
    ----------
    value : object, optional
        Original scalar or a display explanation for incomplete content.
    state : str, optional
        Completeness state.
    sources : sequence of str, optional
        Original source locators.
    kind : str, optional
        Scalar, object or array shape.
    children : dict or None, optional
        Recognized child nodes in supplied order.

    Returns
    -------
    dict
        Source tree node used only for this inspection.
    """
    return {"value": value, "state": state, "sources": list(sources), "kind": kind, "children": children or {}}


def _identity(node):
    """
    Compare source aliases without converting numeric text or merging value types

    Parameters
    ----------
    node : dict
        Already bounded source tree.

    Returns
    -------
    tuple
        Exact typed identity, including incomplete states.
    """
    children = node["children"]
    if children:
        keys = sorted(children) if node["kind"] == "object" else children
        return node["kind"], node["state"], tuple((key, _identity(children[key])) for key in keys)
    value = node["value"]
    return node["kind"], node["state"], type(value).__name__, value


def _complete(node):
    """
    Reject shortened or ambiguous descendants when resolving functional aliases

    Parameters
    ----------
    node : dict
        Bounded source tree.

    Returns
    -------
    bool
        Whether all contents were inspected without ambiguity or truncation.
    """
    return node["state"] not in {"ambiguous", "truncated"} and all(_complete(child) for child in node["children"].values())


def _merge_sources(first, second, budget):
    """
    Retain both original locators when complete aliases have identical values

    Parameters
    ----------
    first : dict
        Mutable retained node.
    second : dict
        Equivalent node from another original key.
    budget : InspectionBudget
        Records any shortened source locator lists.
    """
    sources = list(dict.fromkeys([*first["sources"], *second["sources"]]))
    if len(sources) > 8:
        budget.limits["shortened_values"] += 1
        first["state"] = "truncated"
    first["sources"] = sources[:8]
    for key, child in first["children"].items():
        _merge_sources(child, second["children"][key], budget)


def _recognize(value, shape, source, budget, depth=0, *, phase_scope_only=False):
    """
    Apply shared schema naming and wrapper rules while retaining exact leaf values

    This traversal deliberately does not use numeric coercion from the general
    metadata view because precise numeric text and original types are evidence here.

    Parameters
    ----------
    value : object
        Original JSON value at this parent.
    shape : dict or None
        Shared trusted schema hints, absent inside arbitrary parameter objects.
    source : str
        Original path to this value.
    budget : InspectionBudget
        Request wide traversal allowance.
    depth : int, optional
        Current nesting level.
    phase_scope_only : bool, optional
        Skip unrelated phase metadata when no duplicate phase parent needs checking.

    Returns
    -------
    dict
        Bounded recognized tree with exact values and original locators.
    """
    if not budget.enter(depth):
        return _node("Content omitted at the inspection limit", state="truncated", sources=[source])
    if shape and shape["single_value"]:
        while isinstance(value, list) and len(value) == 1:
            depth += 1
            source = _path(source, 0)
            if not budget.enter(depth):
                return _node("Content omitted at the inspection limit", state="truncated", sources=[source])
            value = value[0]
    if value is _MISSING or value is None or (isinstance(value, str) and not value.strip()):
        return _node(value, state="not_supplied", sources=[source])
    if isinstance(value, dict):
        if not value:
            return _node(value, state="not_supplied", sources=[source], kind="object")
        children = {}
        fields = shape["fields"] if shape else ()
        properties = shape["properties"] if shape else {}
        scoped_phase = phase_scope_only and shape is _metadata_shape()["properties"]["phase"]["items"]
        for key, child in value.items():
            if budget.visited >= MAX_VISITED_NODES:
                budget.limits["node_limits"] += 1
                return _node(state="truncated", sources=[source], kind="object", children=children)
            name = matched_field_name(key, fields)
            if scoped_phase and name not in {"phase_name", "constitutive_model"}:
                budget.enter(depth + 1)
                continue
            recognized = _recognize(child, properties.get(name), _path(source, key), budget, depth + 1,
                                    phase_scope_only=phase_scope_only)
            if name not in children:
                children[name] = recognized
                continue
            previous = children[name]
            if _complete(previous) and _complete(recognized) and _identity(previous) == _identity(recognized):
                _merge_sources(previous, recognized, budget)
            elif name in fields and name in DESCRIPTIVE_FIELDS and _complete(previous) and _complete(recognized):
                entries = previous["children"] if previous.get("descriptions") else {0: previous}
                entries[len(entries)] = recognized
                combined = _node(sources=[*previous["sources"], *recognized["sources"]][:8], kind="array", children=entries)
                combined["descriptions"] = True
                children[name] = combined
            else:
                sources = list(dict.fromkeys([*previous["sources"], *recognized["sources"]]))[:8]
                children[name] = _node("Conflicting aliases; inspect the original fields", state="ambiguous", sources=sources)
        return _node(sources=[source], kind="object", children=children)
    if isinstance(value, list):
        if not value:
            return _node(value, state="not_supplied", sources=[source], kind="array")
        children = {}
        for index, child in enumerate(value[:MAX_ARRAY_ENTRIES]):
            if budget.visited >= MAX_VISITED_NODES:
                budget.limits["node_limits"] += 1
                return _node(state="truncated", sources=[source], kind="array", children=children)
            children[index] = _recognize(child, shape.get("items") if shape else None, _path(source, index), budget, depth + 1,
                                         phase_scope_only=phase_scope_only)
        omitted = max(0, len(value) - MAX_ARRAY_ENTRIES)
        budget.limits["omitted_array_entries"] += omitted
        return _node(sources=[source], kind="array", children=children, state="truncated" if omitted else "recorded")
    if isinstance(value, float) and not math.isfinite(value):
        return _node("Non-finite numeric value", state="ambiguous", sources=[source])
    return _node(value, sources=[source])


def _cell(node, object_pk, budget):
    """
    Format a bounded typed value and retain its completeness separately

    Parameters
    ----------
    node : dict
        Terminal node or an incomplete container marker.
    object_pk : int
        Record owning this cell.
    budget : InspectionBudget
        Receives rendering omissions.

    Returns
    -------
    dict
        Template cell and internal exact comparison token.
    """
    value, state = node["value"], node["state"]
    if value is _MISSING:
        display = "Additional content omitted" if state == "truncated" else "Not supplied"
        value_type = node["kind"] if node["kind"] != "scalar" else "missing"
    else:
        display = json.dumps(value, ensure_ascii=False, allow_nan=False)
        value_type = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object", type(None): "null"}[type(value)]
        if state in {"ambiguous", "truncated"}:
            display = value if isinstance(value, str) else display
    sources = node["sources"][:8]
    if len(display) > MAX_DISPLAY_CHARACTERS or any(len(source) > MAX_DISPLAY_CHARACTERS for source in sources):
        budget.limits["shortened_values"] += 1
        display = display[:MAX_DISPLAY_CHARACTERS - 1] + "…" if len(display) > MAX_DISPLAY_CHARACTERS else display
        sources = [source[:MAX_DISPLAY_CHARACTERS - 1] + "…" if len(source) > MAX_DISPLAY_CHARACTERS else source for source in sources]
        state = "truncated"
    return {"object_pk": object_pk, "value": display, "value_type": value_type, "state": state,
            "state_label": STATE_LABELS[state], "source_paths": sources,
            "token": _identity(node) if state == "recorded" else None}


def _flatten(node, path, group, output, object_pk, budget, inherited="", label=""):
    """
    Keep positional leaf rows and explicit markers for uninspected descendants

    Parameters
    ----------
    node : dict
        Recognized source subtree.
    path : str
        Canonical path retaining exact freeform keys.
    group : str
        Human readable phase, condition or units section.
    output : dict
        Ordered rows for one selected record.
    object_pk : int
        Source record identifier.
    budget : InspectionBudget
        Shared rendering allowance.
    inherited : str, optional
        Incomplete ancestor state that must not become a complete leaf match.
    label : str, optional
        Exact final field name with any following array indices.
    """
    label = label or path.rsplit(".", 1)[-1]
    state = inherited or (node["state"] if node["state"] in {"ambiguous", "truncated"} else "")
    if node["children"]:
        if state:
            marker = _node(state=state, sources=node["sources"], kind=node["kind"])
            output[path] = (group, _cell(marker, object_pk, budget), label)
        for key, child in node["children"].items():
            child_label = f"{label}[{key}]" if isinstance(key, int) else key
            _flatten(child, _path(path, key), group, output, object_pk, budget, state, child_label)
    else:
        if state:
            node = {**node, "state": state}
        output[path] = (group, _cell(node, object_pk, budget), label)


def _extract_record(obj, budget):
    """
    Extract only model, loading and units rows from the selected record

    Parameters
    ----------
    obj : JSONData
        Locked accessible record with its original JSON loaded.
    budget : InspectionBudget
        Allowance shared across selected records.

    Returns
    -------
    tuple
        Bounded record labels and positional field cells.
    """
    shape = _metadata_shape()
    source = obj.data if isinstance(obj.data, dict) else {}
    selected = {}
    for key, value in source.items():
        if not budget.enter(0):
            break
        name = matched_field_name(key, shape["fields"])
        if name in {"phase", "mechanical_BC", "units", "title", "identifier"}:
            selected[key] = value
    phase_sources = sum(matched_field_name(key, shape["fields"]) == "phase" for key in selected)
    root = _recognize(selected, shape, "", budget, phase_scope_only=phase_sources == 1)
    children = root["children"]
    rows = {}
    missing = _node(state="not_supplied")
    phase = children.get("phase", missing)
    if phase["kind"] != "array" or not phase["children"]:
        _flatten(phase, "phase", "Phase model settings", rows, obj.pk, budget)
    else:
        if phase["state"] != "recorded":
            _flatten(_node(state=phase["state"], sources=phase["sources"]), "phase", "Phase model settings", rows, obj.pk, budget)
        for index, entry in phase["children"].items():
            base = f"phase[{index}]"
            group = f"Phase {index + 1} · model settings"
            if entry["kind"] != "object" or not entry["children"]:
                _flatten(entry, base, group, rows, obj.pk, budget)
                continue
            inherited = "truncated" if phase["state"] == "truncated" else ""
            if entry["state"] in {"ambiguous", "truncated"}:
                inherited = entry["state"]
            _flatten(entry["children"].get("phase_name", missing), base + ".phase_name", group, rows, obj.pk, budget, inherited)
            model = entry["children"].get("constitutive_model", missing)
            if model["kind"] == "object" and model["children"]:
                model_state = inherited or (model["state"] if model["state"] != "recorded" else "")
                if model_state:
                    _flatten(_node(state=model_state, sources=model["sources"]), base + ".constitutive_model", group, rows, obj.pk, budget)
                for name, child in model["children"].items():
                    child_group = f"Phase {index + 1} · recorded model units" if name == "units" else group
                    _flatten(child, _path(base + ".constitutive_model", name), child_group, rows, obj.pk, budget, model_state, name)
                if "units" not in model["children"]:
                    _flatten(missing, base + ".constitutive_model.units", f"Phase {index + 1} · recorded model units", rows, obj.pk, budget)
            else:
                _flatten(model, base + ".constitutive_model", group, rows, obj.pk, budget, inherited)
    boundary = children.get("mechanical_BC", missing)
    if boundary["kind"] == "array" and boundary["children"]:
        if boundary["state"] != "recorded":
            _flatten(_node(state=boundary["state"], sources=boundary["sources"]), "mechanical_BC", "Loading conditions", rows, obj.pk, budget)
        for index, entry in boundary["children"].items():
            inherited = "truncated" if boundary["state"] == "truncated" else ""
            _flatten(entry, f"mechanical_BC[{index}]", f"Loading condition {index + 1}", rows, obj.pk, budget, inherited)
    else:
        _flatten(boundary, "mechanical_BC", "Loading conditions", rows, obj.pk, budget)
    _flatten(children.get("units", missing), "units", "Recorded top-level units", rows, obj.pk, budget)
    if root["state"] == "truncated":
        _flatten(_node(state="truncated"), "inspection", "Inspection scope", rows, obj.pk, budget)
    record = {"pk": obj.pk, "title": f"Object {obj.pk}", "identifier": "", "detail_url": reverse("json_data_detail", args=[obj.pk])}
    for name in ("title", "identifier"):
        label = children.get(name, missing)
        if label["state"] == "recorded" and isinstance(label["value"], str) and label["value"].strip():
            record[name] = label["value"][:240]
    return record, rows


def _empty_context():
    """
    Create a safe result with no selected record metadata

    Returns
    -------
    dict
        Complete empty template contract.
    """
    return {"ready": False, "error": "", "rows": [], "objects": [], "differences": [], "limited": False,
            "counts": {"same": 0, "different": 0, "incomplete": 0, "total": 0},
            "limits": {}, "limit_reasons": [], "visited_nodes": 0, "scope_note": SCOPE_NOTE}


def _finish_context(context, extracted, budget):
    """
    Join positional fields without declaring incomplete cells equal

    Parameters
    ----------
    context : dict
        Result receiving authorized records and rows.
    extracted : list of tuple
        Selected record labels and per-record row maps in reference order.
    budget : InspectionBudget
        Collected traversal and rendering omissions.

    Returns
    -------
    dict
        Ready native table context with factual differences and explicit limits.
    """
    from hashlib import sha256

    paths = {}
    for record, fields in extracted:
        context["objects"].append(record)
        for path, (group, _, label) in fields.items():
            paths.setdefault(path, (group, label))
    budget.limits["omitted_rows"] = max(0, len(paths) - MAX_PARAMETER_ROWS)
    for path, (group, label) in list(paths.items())[:MAX_PARAMETER_ROWS]:
        cells = []
        for record, fields in extracted:
            cell = fields[path][1] if path in fields else _cell(_node(state="not_supplied"), record["pk"], budget)
            cells.append(dict(cell))
        status = "incomplete"
        if all(cell["state"] == "recorded" for cell in cells):
            status = "same" if all(cell["token"] == cells[0]["token"] for cell in cells[1:]) else "different"
        for cell in cells:
            cell.pop("token", None)
        display_path = path[:MAX_DISPLAY_CHARACTERS - 1] + "…" if len(path) > MAX_DISPLAY_CHARACTERS else path
        key = sha256(path.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]
        row = {"path": display_path, "key": key, "id": "study-parameter-" + key,
               "label": label[:MAX_DISPLAY_CHARACTERS], "group": group, "status": status,
               "status_label": STATUS_LABELS[status], "cells": cells}
        context["rows"].append(row)
        context["counts"][status] += 1
        if status != "same" and len(context["differences"]) < 3:
            context["differences"].append({"path": display_path, "key": key, "id": row["id"],
                                           "field_label": row["label"], "status": status,
                                           "label": STATUS_LABELS[status], "cells": cells})
    reasons = []
    for key, label in (("omitted_rows", "additional field rows omitted"), ("omitted_array_entries", "array entries omitted"),
                       ("depth_limits", "branches stopped at the depth limit"), ("node_limits", "branches stopped at the traversal limit"),
                       ("shortened_values", "values or source paths shortened")):
        if budget.limits[key]:
            reasons.append(f"{budget.limits[key]} {label}.")
    context.update(ready=True, limits=budget.limits, limited=bool(reasons), limit_reasons=reasons, visited_nodes=budget.visited)
    context["counts"]["total"] = len(context["rows"])
    return context


def build_parameter_context(request, ids, *, collection=None, selection_token=""):
    """
    Inspect a complete authorized comparison within byte and traversal allowances

    Collection ownership and ordered object locks precede fresh access checks.
    Temporary selections recheck every current member before any JSON is loaded.

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request with its browser session.
    ids : sequence of int
        Two to four distinct selected records in reference order.
    collection : ResearchCollection or None, optional
        Saved collection, whose ownership is independently checked here.
    selection_token : str, optional
        Current owner and session bound temporary selection token.

    Returns
    -------
    dict
        Bounded native comparison or a complete failure without partial values.
    """
    context = _empty_context()
    try:
        if (not request.user.is_authenticated or not isinstance(ids, (list, tuple)) or not 2 <= len(ids) <= 4
                or any(type(pk) is not int or not 0 < pk <= 9223372036854775807 for pk in ids)
                or len(set(ids)) != len(ids) or (collection is not None) == bool(selection_token)):
            raise ValueError(UNAVAILABLE_PARAMETERS)
        with transaction.atomic():
            if collection is not None:
                owned = _owned_collection(request, collection.pk, lock=True)
                objects = accessible_objects(request.user).filter(research_collections=owned)
            else:
                members = _selection_ids(request, selection_token)
                objects = _validate_access(request.user, members)
            selected = objects.filter(pk__in=ids).order_by("pk")
            if list(selected.select_for_update().values_list("pk", flat=True)) != sorted(ids):
                raise ValueError(UNAVAILABLE_PARAMETERS)
            if list(selected.values_list("pk", flat=True)) != sorted(ids):
                raise ValueError(UNAVAILABLE_PARAMETERS)
            if collection is None:
                members = _selection_ids(request, selection_token)
                _validate_access(request.user, members)
                if not set(ids).issubset(members):
                    raise ValueError(UNAVAILABLE_PARAMETERS)
            postgres = connections[selected.db].vendor == "postgresql"
            byte_length = Func(Cast(F("data"), TextField() if postgres else BinaryField()),
                               function="OCTET_LENGTH" if postgres else "LENGTH", output_field=BigIntegerField())
            sizes = list(selected.annotate(parameter_raw_bytes=byte_length).values_list("pk", "parameter_raw_bytes"))
            if len(sizes) != len(ids):
                raise ValueError(UNAVAILABLE_PARAMETERS)
            if any(size is None or size <= 0 for _, size in sizes) or sum(size for _, size in sizes) > MAX_PARAMETER_BYTES:
                context.update(error=PARAMETER_LIMIT_MESSAGE, limited=True, limit_reasons=[PARAMETER_LIMIT_MESSAGE])
                context["objects"] = [{"pk": pk, "title": f"Object {pk}", "identifier": "",
                                       "detail_url": reverse("json_data_detail", args=[pk])} for pk in ids]
                return context
            budget = InspectionBudget()
            extracted = {}
            for obj in selected.only("pk", "data").iterator(chunk_size=1):
                extracted[obj.pk] = _extract_record(obj, budget)
            if set(extracted) != set(ids):
                raise ValueError(UNAVAILABLE_PARAMETERS)
            return _finish_context(context, [extracted[pk] for pk in ids], budget)
    except (ValueError, Http404):
        context = _empty_context()
        context["error"] = UNAVAILABLE_PARAMETERS
        return context
