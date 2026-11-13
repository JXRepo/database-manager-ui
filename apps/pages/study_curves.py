"""
Read bounded recorded mechanical curves for accessible study selections
"""

import json
import math

from django.contrib.auth.decorators import login_required
from django.db import connections, transaction
from django.db.models import BigIntegerField, BinaryField, F, Func, TextField
from django.db.models.functions import Cast
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.dyn_api.metadata_compat import field_name, metadata_view, unwrap_single_value

from .research_collections import _owned_collection, _selection_ids, _validate_access, accessible_objects
from .study_comparison import UNIT_FIELDS, parse_comparison_ids


CURVE_COMPONENTS = ("equivalent", "11", "22", "33", "12", "13", "23")
CURVE_STRAINS = ("total", "plastic")
MAX_CURVE_BYTES = 16 * 1024 * 1024
MAX_CURVE_POINTS = 100000
UNAVAILABLE_CURVES = "Some selected objects are unavailable. Choose accessible records from this workspace again."
CURVE_LIMIT_MESSAGE = "These records exceed the comparison curve limit. Choose fewer or smaller records, or inspect their individual detail pages."
_MISSING = object()
_AMBIGUOUS = object()
_SERIES_NAMES = {field_name(f"{prefix}_{component}") for prefix in ("stress", "strain", "plastic_strain")
                 for component in CURVE_COMPONENTS[1:]}
_SERIES_NAMES.update(map(field_name, ("equivalent_stress", "equivalent_strain", "equivalent_plastic_strain")))
_SCALAR_UNITS = set(map(field_name, UNIT_FIELDS))


class CurveLimit(ValueError):
    """
    Stop an oversized comparison without returning partial curve arrays
    """


def curve_parameters(params):
    """
    Validate one explicit mechanical component and strain group

    Parameters
    ----------
    params : QueryDict or dict
        Query or signed workspace controls.

    Returns
    -------
    dict
        Validated selectors including defaults.

    Raises
    ------
    ValueError
        A selector is repeated or unsupported.
    """
    result = {}
    for name, choices, default in (("curve_component", CURVE_COMPONENTS, "equivalent"),
                                    ("curve_strain", CURVE_STRAINS, "total")):
        values = params.getlist(name) if hasattr(params, "getlist") else [params.get(name, default)]
        if not values:
            values = [default]
        if len(values) != 1 or not isinstance(values[0], str) or values[0] not in choices:
            raise ValueError("Choose one supported curve component and strain type.")
        result[name] = values[0]
    return result


def _source_identity(value, name):
    """
    Remove accepted source wrappers without rounding numbers or flattening curves

    Parameters
    ----------
    value : object
        Original source value at a known schema location.
    name : str
        Parent, unit or mechanical series field name.

    Returns
    -------
    object
        Comparable original values with known wrappers and spellings normalized.
    """
    key = field_name(name)
    if key in _SERIES_NAMES:
        return [unwrap_single_value(item) for item in value] if isinstance(value, list) else value
    if key in _SCALAR_UNITS or key in {"units", "totalstrain", "plasticstrain"}:
        value = unwrap_single_value(value)
    if key in {"units", "stress", "totalstrain", "plasticstrain"} and isinstance(value, dict):
        fields = {}
        for child, item in value.items():
            identity = json.dumps(_source_identity(item, child), sort_keys=True, ensure_ascii=True)
            fields.setdefault(field_name(child), set()).add(identity)
        return {child: sorted(items) for child, items in fields.items()}
    return value


def _raw_field(parent, name):
    """
    Detect conflicting original aliases before numeric normalization can hide them

    Parameters
    ----------
    parent : object
        Original object at a known schema parent.
    name : str
        Exact schema field name, ignoring case and separator punctuation.

    Returns
    -------
    object
        Original value or a missing or ambiguous sentinel.
    """
    if parent is _AMBIGUOUS:
        return _AMBIGUOUS
    parent = unwrap_single_value(parent)
    if not isinstance(parent, dict):
        return _MISSING
    values = [value for key, value in parent.items() if field_name(key) == field_name(name)]
    if len(values) > 1:
        serialized = {json.dumps(_source_identity(value, name), sort_keys=True, ensure_ascii=True)
                      for value in values}
        if len(serialized) > 1:
            return _AMBIGUOUS
    return values[0] if values else _MISSING


def _numeric_series(value):
    """
    Accept complete finite numeric arrays without sorting or removing samples

    Parameters
    ----------
    value : object
        A recognized mechanical result series.

    Returns
    -------
    bool
        Whether every supplied sample is a finite number.
    """
    if not isinstance(value, list) or not value:
        return False
    try:
        return all(type(item) in (int, float) and math.isfinite(item) for item in value)
    except OverflowError:
        return False


def _series(data, group_name, component, *, count):
    """
    Select a recorded series or the existing eligible equivalent calculation

    Parameters
    ----------
    data : dict
        Shared metadata compatibility view.
    group_name : str
        One top-level mechanical result group.
    component : str
        Explicit tensor component or equivalent.
    count : int
        Requested paired samples, with zero checking availability without calculation.

    Returns
    -------
    tuple
        Values, calculation flag, state, source path, inspected fields and full sample count.
    """
    from .views import _calculate_equivalent_strain, _calculate_equivalent_stress

    prefix = {"stress": "stress", "total_strain": "strain", "plastic_strain": "plastic_strain"}[group_name]
    key = ("equivalent_" + prefix) if component == "equivalent" else f"{prefix}_{component}"
    path = f"{group_name}.{key}"
    group = data.get(group_name)
    if not isinstance(group, dict):
        return [], False, "missing", path, [path], 0
    calculated = False
    inspected = [path]
    if key in group:
        values = group[key]
    elif component == "equivalent":
        keys = [f"{prefix}_{part}" for part in CURVE_COMPONENTS[1:]]
        inspected += [f"{group_name}.{name}" for name in keys]
        arrays = {}
        for part, name in zip(CURVE_COMPONENTS[1:], keys):
            values = group.get(name)
            if not _numeric_series(values):
                state = "missing" if values is None or values == [] else "invalid"
                return [], False, state, path, inspected, 0
            arrays[part] = values
        available_count = min(map(len, arrays.values()))
        if not count:
            return [], True, "ready", path, inspected, available_count
        calculate = _calculate_equivalent_stress if group_name == "stress" else _calculate_equivalent_strain
        try:
            values = calculate({part: values[:count] for part, values in arrays.items()})
        except (OverflowError, ValueError):
            return [], True, "invalid", path, inspected, available_count
        calculated = True
    else:
        return [], False, "missing", path, inspected, 0
    if not _numeric_series(values):
        state = "missing" if values is None or values == [] else "invalid"
        return [], calculated, state, path, inspected, 0
    if not calculated:
        available_count = len(values)
    return values[:count], calculated, "ready", path, inspected, available_count


def _unit(value, kind):
    """
    Keep explicit unit labels and recognize only unambiguous overlay units

    Parameters
    ----------
    value : object
        Supplied unit value at the known units parent.
    kind : str
        Stress or Strain.

    Returns
    -------
    tuple
        Display label and recognized unit identity, empty when unsupported.
    """
    value = unwrap_single_value(value)
    if type(value) in (int, float) and value == 1 and kind == "Strain":
        return "1", "1"
    if not isinstance(value, str) or not value.strip():
        return "Not supplied", ""
    value = value.strip()
    if kind == "Stress":
        known = value if value in {"Pa", "kPa", "MPa", "GPa"} else ""
    else:
        known = {"1": "1", "dimensionless": "1", "unitless": "1", "%": "%"}.get(value.casefold(), "")
    return value[:120], known


def _label(value, fallback):
    """
    Render bounded supplied record labels without copying arbitrary metadata

    Parameters
    ----------
    value : object
        Recognized title or identifier.
    fallback : str
        Label used when no text is supplied.

    Returns
    -------
    str
        Bounded text suitable for a curve legend.
    """
    if isinstance(value, list):
        value = "; ".join(item for item in value[:8] if isinstance(item, str))
    return value[:240] if isinstance(value, str) and value.strip() else fallback


def _record_curve(obj, component, strain):
    """
    Prepare one complete paired curve and explain missing or conflicting sources

    Parameters
    ----------
    obj : JSONData
        Accessible locked record with its original JSON loaded within the byte limit.
    component : str
        Validated component selection.
    strain : str
        Total or plastic strain.

    Returns
    -------
    dict
        Curve arrays, source paths, units and an explicit completeness state.
    """
    conflicts = []
    data = metadata_view(obj.data, conflicts=conflicts)
    group = "total_strain" if strain == "total" else "plastic_strain"
    x, calculated_x, x_state, x_path, x_sources, x_count = _series(data, group, component, count=0)
    y, calculated_y, y_state, y_path, y_sources, y_count = _series(data, "stress", component, count=0)
    units = data.get("units")
    units = units if isinstance(units, dict) else {}
    x_unit, x_identity = _unit(units.get("Strain"), "Strain")
    y_unit, y_identity = _unit(units.get("Stress"), "Stress")
    paths = [*x_sources, *y_sources, "units.Strain", "units.Stress"]
    normalized = [field_name(path) for path in paths]
    ambiguous = any(
        candidate.startswith(field_name(conflict)) or field_name(conflict).startswith(candidate)
        for candidate in normalized for pair in conflicts for conflict in pair
    )
    for path in paths:
        parent, name = path.split(".", 1)
        if _raw_field(_raw_field(obj.data, parent), name) is _AMBIGUOUS:
            ambiguous = True
            break
    state = "ready"
    error = ""
    if ambiguous:
        state, error = "ambiguous", "Conflicting source fields prevent plotting this record. Inspect its original metadata."
    elif "invalid" in {x_state, y_state}:
        state, error = "invalid", "The selected component contains invalid or non-finite values. Inspect this record's source arrays."
    elif "missing" in {x_state, y_state}:
        state, error = "missing", "This record does not supply the selected stress and strain pair. Choose another component or inspect its detail page."
    count = min(x_count, y_count) if state == "ready" else 0
    if count > MAX_CURVE_POINTS:
        raise CurveLimit(CURVE_LIMIT_MESSAGE)
    if count:
        x, calculated_x, x_state, _, _, _ = _series(data, group, component, count=count)
        y, calculated_y, y_state, _, _, _ = _series(data, "stress", component, count=count)
        if x_state != "ready" or y_state != "ready":
            state, error = "invalid", "The selected equivalent calculation produced invalid values. Inspect this record's source arrays."
            count = 0
    return {
        "pk": obj.pk, "title": _label(data.get("title"), "Untitled data object"),
        "identifier": _label(data.get("identifier"), ""), "component": component, "strain": strain,
        "x": x[:count], "y": y[:count], "x_count": x_count, "y_count": y_count, "paired_count": count,
        "x_path": x_path, "y_path": y_path,
        "x_unit": x_unit, "y_unit": y_unit, "x_unit_identity": x_identity, "y_unit_identity": y_identity,
        "x_label": ("Total strain" if strain == "total" else "Plastic strain") + f" ({component})",
        "y_label": f"Stress ({component})", "calculated_x": calculated_x, "calculated_y": calculated_y,
        "state": state, "error": error, "detail_url": reverse("json_data_detail", args=[obj.pk]),
    }


def _json_response(payload, status=200):
    """
    Return private curve data without browser or intermediary caching

    Parameters
    ----------
    payload : dict
        Safe result or generic error response.
    status : int, optional
        HTTP response status.

    Returns
    -------
    JsonResponse
        Strict finite JSON with private response headers.
    """
    response = JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False, "allow_nan": False})
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _curve_response(request, objects, *, selection_ids=None):
    """
    Check complete access and real JSON bytes before loading any selected arrays

    Parameters
    ----------
    request : HttpRequest
        Authenticated request inside the endpoint transaction.
    objects : QuerySet
        Current accessible collection or selection members.
    selection_ids : list of int or None, optional
        Entire temporary membership to recheck after selected object locks.

    Returns
    -------
    JsonResponse
        Complete bounded comparison, or an error without any record metadata.
    """
    try:
        options = curve_parameters(request.GET)
        ids = parse_comparison_ids(request.GET)
        if not 2 <= len(ids) <= 4:
            raise ValueError("Choose two to four accessible records before loading comparison curves.")
        selected = objects.filter(pk__in=ids).order_by("pk")
        if list(selected.select_for_update().values_list("pk", flat=True)) != sorted(ids):
            raise ValueError(UNAVAILABLE_CURVES)
        if selected.count() != len(ids):
            raise ValueError(UNAVAILABLE_CURVES)
        if selection_ids is not None:
            _validate_access(request.user, selection_ids)
        postgres = connections[objects.db].vendor == "postgresql"
        byte_length = Func(
            Cast(F("data"), TextField() if postgres else BinaryField()),
            function="OCTET_LENGTH" if postgres else "LENGTH", output_field=BigIntegerField(),
        )
        sizes = list(selected.annotate(curve_raw_bytes=byte_length).values_list("pk", "curve_raw_bytes"))
        if len(sizes) != len(ids):
            raise ValueError(UNAVAILABLE_CURVES)
        if any(size is None or size <= 0 for _, size in sizes) or sum(size for _, size in sizes) > MAX_CURVE_BYTES:
            raise CurveLimit(CURVE_LIMIT_MESSAGE)
        records = {}
        total_points = 0
        for obj in selected.only("pk", "data").iterator(chunk_size=1):
            record = _record_curve(obj, options["curve_component"], options["curve_strain"])
            total_points += record["paired_count"]
            if total_points > MAX_CURVE_POINTS:
                raise CurveLimit(CURVE_LIMIT_MESSAGE)
            records[obj.pk] = record
        if set(records) != set(ids):
            raise ValueError(UNAVAILABLE_CURVES)
        ordered = [records[pk] for pk in ids]
        overlay_reason = ""
        if any(record["state"] != "ready" for record in ordered):
            overlay_reason = "Every selected record needs the chosen stress and strain pair before curves can be overlaid."
        elif any(not record["x_unit_identity"] or not record["y_unit_identity"] for record in ordered):
            overlay_reason = "Overlay requires explicit supported stress and strain units in every selected record."
        elif len({(record["x_unit_identity"], record["y_unit_identity"]) for record in ordered}) != 1:
            overlay_reason = "The recorded units differ. Inspect these curves separately; no unit conversion is applied."
        return _json_response({
            "ok": True, "selection": ids, "component": options["curve_component"], "strain": options["curve_strain"],
            "records": ordered, "overlay_allowed": not overlay_reason, "overlay_reason": overlay_reason,
        })
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc), "records": []},
                              status=413 if isinstance(exc, CurveLimit) else 400)


@login_required
@require_GET
@transaction.atomic
def collection_study_curves(request, pk):
    """
    Load curves from an owned collection with stable membership and access

    Parameters
    ----------
    request : HttpRequest
        Authenticated curve request.
    pk : int
        Collection belonging to the viewer.

    Returns
    -------
    JsonResponse
        Complete selected curve data or an explicit failure.
    """
    collection = _owned_collection(request, pk, lock=True)
    objects = accessible_objects(request.user).filter(research_collections=collection)
    return _curve_response(request, objects)


@login_required
@require_GET
@transaction.atomic
def selection_study_curves(request, token):
    """
    Load selected curves only while every temporary member remains accessible

    Parameters
    ----------
    request : HttpRequest
        Authenticated request bound to the current browser session.
    token : str
        Temporary selection owned by the viewer and session.

    Returns
    -------
    JsonResponse
        Complete selected curve data or an explicit stale-selection response.
    """
    ids = _selection_ids(request, token)
    try:
        objects = _validate_access(request.user, ids)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc), "records": []}, status=400)
    return _curve_response(request, objects, selection_ids=ids)
