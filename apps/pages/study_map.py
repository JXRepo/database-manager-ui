"""
Map explicitly recorded scalar parameters without inferring scientific equivalence
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from urllib.parse import urlencode

from django.core.paginator import Paginator

from apps.dyn_api.metadata_compat import NUMBER_TEXT, field_name, unwrap_single_value


MAP_VERSION = 1
MAP_PARAMETERS = {"map_x", "map_y", "map_unit", "map_x_page", "map_y_page", "map_cell", "map_row"}
AXIS_LABELS = {"temperature": "Global temperature", "discretization_count": "Discretization count"}
AXIS_WINDOW = 8
MAX_NUMERIC_CHARACTERS = 512
MAX_UNIT_CHARACTERS = 80
UNIT_FIELDS = ("Stress", "Strain", "Length", "Force", "Angle", "Temperature")
SUPPORTED_TEMPERATURE_UNITS = {
    "k", "kelvin", "kelvins", "c", "celsius", "degc", "degreecelsius", "degreescelsius",
    "f", "fahrenheit", "degf", "degreefahrenheit", "degreesfahrenheit",
}
EXCLUSION_LABELS = {
    "ambiguous": "Conflicting parameter or unit fields",
    "invalid": "Invalid or unsupported scalar values",
    "missing": "Missing parameter or temperature unit",
    "unsupported_unit": "Unsupported temperature unit",
}
_AMBIGUOUS = object()
_INVALID = object()


def _token(*values):
    """
    Keep numeric and unit identities bounded in native and signed navigation

    Parameters
    ----------
    *values : str
        Exact scalar identities in their specified order.

    Returns
    -------
    str
        Stable hexadecimal digest without raw uploaded text.
    """
    text = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _known_children(value, names):
    """
    Compare known child names and wrappers without interpreting their scalar values

    Unknown names and containers retain their original keys and shape. This view
    exists only to compare duplicate unit containers and never changes stored data.

    Parameters
    ----------
    value : object
        Unwrapped original parent value.
    names : tuple of str
        Explicit schema fields permitted to normalize at this parent.

    Returns
    -------
    object
        Temporary comparison view, original nonobject value, or a conflict marker.
    """
    if not isinstance(value, dict):
        return value
    recognized = {field_name(name): name for name in names}
    result = {}
    for key, child in value.items():
        canonical = recognized.get(field_name(key))
        if canonical is None:
            result[key] = child
            continue
        child = unwrap_single_value(child)
        if canonical in result and json.dumps(result[canonical], sort_keys=True) != json.dumps(child, sort_keys=True):
            return _AMBIGUOUS
        result[canonical] = child
    return result


def _original_field(parent, name, known_children=()):
    """
    Read a scalar at its schema parent while rejecting disagreeing aliases

    Parameters
    ----------
    parent : object
        Original parent value, possibly wrapped in singleton lists.
    name : str
        Known schema field name.
    known_children : tuple of str, optional
        Known children whose spelling and wrappers may be compared across containers.

    Returns
    -------
    object
        Original unwrapped value, None, or an explicit invalid or ambiguous marker.
    """
    parent = unwrap_single_value(parent)
    if parent is _AMBIGUOUS or parent is _INVALID:
        return parent
    if parent is None or parent == "" or parent == [] or parent == {}:
        return None
    if not isinstance(parent, dict):
        return _INVALID
    values = [unwrap_single_value(value) for key, value in parent.items() if field_name(key) == field_name(name)]
    if not values:
        return None
    if len(values) > 1:
        comparable = [_known_children(value, known_children) for value in values] if known_children else values
        if any(value is _AMBIGUOUS for value in comparable):
            return _AMBIGUOUS
        serialized = {json.dumps(value, sort_keys=True, ensure_ascii=True) for value in comparable}
        if len(serialized) != 1:
            return _AMBIGUOUS
    return values[0]


def _decimal_identity(number):
    """
    Canonicalize finite decimals without the current Decimal precision context

    Parameters
    ----------
    number : Decimal
        An already validated finite number.

    Returns
    -------
    str
        Exact compact identity that equates numeric spelling variants and signed zero.
    """
    if not number:
        return "0"
    sign, digits, exponent = number.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(map(str, digits))
    return ("-" if sign else "") + coefficient + "e" + str(exponent)


def _numeric_projection(value, path):
    """
    Preserve original scalar text and type beside an exact numeric coordinate

    Parameters
    ----------
    value : object
        Original numeric field after supported singleton unwrapping.
    path : str
        Canonical schema path for this field.

    Returns
    -------
    dict
        Bounded scalar projection with an explicit completeness state.
    """
    result = {"path": path, "state": "missing", "value": "", "value_type": "", "number": "",
              "unit": "", "unit_path": ""}
    if value is _AMBIGUOUS:
        result["state"] = "ambiguous"
        return result
    if value is None or value == "" or value == [] or value == {} or isinstance(value, str) and not value.strip():
        return result
    result["state"] = "invalid"
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return result
    try:
        text = str(value)
    except ValueError:
        return result
    if len(text) > MAX_NUMERIC_CHARACTERS or not NUMBER_TEXT.fullmatch(text.strip()):
        return result
    try:
        number = Decimal(text.strip())
    except InvalidOperation:
        return result
    if not number.is_finite():
        return result
    result.update(state="recorded", value=text, value_type="numeric_text" if isinstance(value, str) else type(value).__name__,
                  number=_decimal_identity(number))
    return result


def build_map_projection(raw_data, normalized=None, conflicts=()):
    """
    Extract only global temperature and discretization count from original values

    Compatibility recognition is limited to known fields at their actual parents.
    Temperature unit spellings remain separate and no unit conversion is performed.

    Parameters
    ----------
    raw_data : object
        Original uploaded record, retained unchanged.
    normalized : dict or None, optional
        Existing compatibility view, unused for numeric text or type interpretation.
    conflicts : sequence of tuple, optional
        Compatibility conflicts already discovered while preparing the summary.

    Returns
    -------
    dict
        Versioned bounded scalar fields without original containers or arrays.
    """
    temperature = _numeric_projection(_original_field(raw_data, "global_temperature"), "global_temperature")
    count = _numeric_projection(_original_field(raw_data, "discretization_count"), "discretization_count")
    units = _original_field(raw_data, "units", UNIT_FIELDS)
    unit = _original_field(units, "Temperature")
    temperature["unit_path"] = "units.Temperature"
    if isinstance(unit, str) and len(unit) <= MAX_UNIT_CHARACTERS:
        temperature["unit"] = unit
    if unit is _AMBIGUOUS:
        temperature["state"] = "ambiguous"
    elif temperature["state"] == "recorded":
        if unit is None or unit == "" or unit == [] or unit == {} or isinstance(unit, str) and not unit.strip():
            temperature["state"] = "missing"
        elif not isinstance(unit, str) or len(unit) > MAX_UNIT_CHARACTERS:
            temperature["state"] = "invalid" if not isinstance(unit, str) else "unsupported_unit"
        elif re.sub(r"[\s°]+", "", unit).casefold() not in SUPPORTED_TEMPERATURE_UNITS:
            temperature["state"] = "unsupported_unit"
    conflict_paths = {field_name(path) for pair in conflicts for path in pair}
    if "discretizationcount" in conflict_paths:
        count["state"] = "ambiguous"
    if conflict_paths.intersection({"globaltemperature", "units", "unitstemperature"}):
        temperature["state"] = "ambiguous"
    return {"version": MAP_VERSION, "fields": {"temperature": temperature, "discretization_count": count}}


def map_parameters(params):
    """
    Validate map controls before retaining them in local or signed navigation

    Scope dependent unit, row and cell identities are checked after all accessible
    summaries are ready. Syntactically valid pages are later clamped to real windows.

    Parameters
    ----------
    params : QueryDict or dict
        Native GET controls or previously validated navigation state.

    Returns
    -------
    dict
        Scalar canonical map controls with defaults omitted.

    Raises
    ------
    ValueError
        Controls are repeated, malformed, unsupported or mutually contradictory.
    """
    values = {}
    for key in MAP_PARAMETERS:
        items = params.getlist(key) if hasattr(params, "getlist") else ([params[key]] if key in params else [])
        if len(items) > 1 or any(not isinstance(item, str) for item in items):
            raise ValueError("Choose each parameter map option once.")
        if items:
            values[key] = items[0]
    x_name = values.get("map_x", "temperature")
    y_name = values.get("map_y", "discretization_count")
    if x_name not in AXIS_LABELS or y_name not in AXIS_LABELS or x_name == y_name:
        raise ValueError("Choose global temperature and discretization count on different axes.")
    for name in ("map_x_page", "map_y_page"):
        value = values.get(name, "1")
        if not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > 2147483647:
            raise ValueError("Choose a valid parameter map page.")
    for name in ("map_unit", "map_cell", "map_row"):
        if name in values and not re.fullmatch(r"[0-9a-f]{64}", values[name]):
            raise ValueError("Choose a current parameter map unit, cell or row.")
    if "map_cell" in values and "map_row" in values:
        raise ValueError("Choose one parameter map cell or row at a time.")
    defaults = {"map_x": "temperature", "map_y": "discretization_count", "map_x_page": "1", "map_y_page": "1"}
    return {key: value for key, value in values.items() if value != defaults.get(key)}


def _number_label(identity):
    """
    Format a complete coordinate without expanding arbitrarily large exponents

    Parameters
    ----------
    identity : str
        Exact canonical finite Decimal identity.

    Returns
    -------
    str
        Decimal or scientific text retaining every recorded significant digit.
    """
    number = Decimal(identity)
    if number == 0:
        return "0"
    if -6 <= number.adjusted() <= 12:
        return format(number, "f")
    return str(number)


def _axis(values, name, requested_page):
    """
    Sort exact coordinates and retain one bounded window with full counts

    Parameters
    ----------
    values : dict
        Numeric identities mapped to their complete accessible member IDs.
    name : str
        Supported axis name.
    requested_page : str
        Validated positive page number.

    Returns
    -------
    dict
        Axis descriptions and at most eight numeric values.
    """
    ordered = sorted(values, key=Decimal)
    page = Paginator(ordered, AXIS_WINDOW).get_page(requested_page)
    return {"name": name, "label": AXIS_LABELS[name], "page": page.number,
            "page_count": page.paginator.num_pages, "total_values": len(ordered),
            "previous_url": "", "next_url": "",
            "values": [{"label": _number_label(value), "key": value, "count": len(values[value])}
                       for value in page.object_list]}


def build_map_context(objects, params, *, base_url, navigation_params=None, preparation_budget=None):
    """
    Build complete parameter coverage and native filters from accessible summaries

    Every accessible member must have a current projection before counts appear.
    The access scope is queried again after preparation so revoked records cannot
    remain in a partially assembled map.

    Parameters
    ----------
    objects : QuerySet
        Current accessible members of the owned collection or temporary selection.
    params : QueryDict or dict
        Requested map controls.
    base_url : str
        Known local workspace route.
    navigation_params : dict or None, optional
        Validated display state including the ordered comparison pins.
    preparation_budget : object or None, optional
        Request allowance shared with other summary consumers.

    Returns
    -------
    dict
        Bounded grid, full counts, selected member IDs and canonical navigation.
    """
    from .collection_graph import CollectionSummaryPending, collection_summaries

    context = {"ready": False, "error": "", "preparation": None, "state": {}, "member_ids": [],
               "counts": {}, "rows": [], "units": [], "x_axis": {}, "y_axis": {}, "max_count": 0,
               "excluded_reasons": [], "selected_label": "", "clear_url": base_url,
               "swap_url": "", "retry_url": "", "form_hidden_fields": []}
    arguments = {key: value for key, value in (navigation_params or {}).items() if key not in MAP_PARAMETERS}
    arguments["panel"] = "map"

    def url(**changes):
        """
        Retain ordered pins while replacing explicit map controls

        Parameters
        ----------
        **changes : object
            Scalar query replacements or None for removal.

        Returns
        -------
        str
            Encoded local workspace URL.
        """
        values = {**arguments, **changes}
        query = urlencode({key: value for key, value in values.items() if value is not None and value != ""})
        return base_url + ("?" + query if query else "")

    context["clear_url"] = url(members_page=None)
    try:
        state = map_parameters(params)
        context["state"] = state
        arguments.update(state)
        context["retry_url"] = url()
        summaries = list(collection_summaries(objects, require_comparison=True, budget=preparation_budget))
        current_ids = set(objects.values_list("pk", flat=True))
        if {row["pk"] for row in summaries} != current_ids:
            raise ValueError("This collection changed while preparing the map. Refresh the parameter map.")
        counts = {"total": len(summaries), "mapped": 0, "selected_unit": 0, "other_units": 0, "excluded": 0,
                  **{name: 0 for name in EXCLUSION_LABELS}}
        unit_records = defaultdict(list)
        for summary in summaries:
            projection = summary.get("parameter_map", {})
            if projection.get("version") != MAP_VERSION or set(projection.get("fields", {})) != set(AXIS_LABELS):
                raise ValueError("Parameter map summaries need preparation. Ask the operator to refresh collection summaries.")
            fields = projection["fields"]
            states = {field["state"] for field in fields.values()}
            reason = next((name for name in EXCLUSION_LABELS if name in states), None)
            if reason:
                counts[reason] += 1
                counts["excluded"] += 1
                continue
            if states != {"recorded"}:
                raise ValueError("Parameter map summaries need preparation. Ask the operator to refresh collection summaries.")
            unit_records[fields["temperature"]["unit"]].append((summary["pk"], fields))
            counts["mapped"] += 1
        unit_by_token = {_token("unit", unit): unit for unit in unit_records}
        requested_unit = state.get("map_unit")
        if requested_unit and requested_unit not in unit_by_token:
            raise ValueError("The selected temperature unit is unavailable. Choose a current unit from the parameter map.")
        selected_unit = (unit_by_token[requested_unit] if requested_unit else
                         min(unit_records, key=lambda unit: (unit.casefold(), unit)) if unit_records else "")
        unit_token = _token("unit", selected_unit) if unit_records else ""
        if unit_token:
            state["map_unit"] = unit_token
            arguments["map_unit"] = unit_token
        x_name = state.get("map_x", "temperature")
        y_name = state.get("map_y", "discretization_count")
        x_values, y_values, cells = defaultdict(list), defaultdict(list), defaultdict(list)
        for pk, fields in unit_records.get(selected_unit, []):
            x_value, y_value = fields[x_name]["number"], fields[y_name]["number"]
            x_values[x_value].append(pk)
            y_values[y_value].append(pk)
            cells[(x_value, y_value)].append(pk)
        counts["selected_unit"] = sum(len(ids) for ids in cells.values())
        counts["other_units"] = counts["mapped"] - counts["selected_unit"]
        x_axis = _axis(x_values, x_name, state.get("map_x_page", "1"))
        y_axis = _axis(y_values, y_name, state.get("map_y_page", "1"))
        for axis in (x_axis, y_axis):
            if axis["name"] == "temperature" and selected_unit:
                axis["label"] += f" ({selected_unit})"
        for key, axis in (("map_x_page", x_axis), ("map_y_page", y_axis)):
            state.pop(key, None)
            arguments.pop(key, None)
            if axis["page"] > 1:
                state[key] = str(axis["page"])
                arguments[key] = state[key]
        cell_tokens = {_token("cell", x_name, y_name, unit_token, x, y): (x, y) for x, y in cells}
        row_tokens = {_token("row", x_name, y_name, unit_token, y): y for y in y_values}
        member_ids = None
        if "map_cell" in state:
            selected = cell_tokens.get(state["map_cell"])
            if selected is None:
                raise ValueError("This map cell is no longer available. Choose a current populated cell.")
            member_ids = cells[selected]
            context["selected_label"] = (f'{x_axis["label"]}: {_number_label(selected[0])}; '
                                         f'{y_axis["label"]}: {_number_label(selected[1])}')
        elif "map_row" in state:
            selected = row_tokens.get(state["map_row"])
            if selected is None:
                raise ValueError("This map row is no longer available. Choose a current populated row.")
            member_ids = y_values[selected]
            context["selected_label"] = f'{y_axis["label"]}: {_number_label(selected)}'
            if y_name != "temperature":
                context["selected_label"] += f" · Temperature unit: {selected_unit}"
        for key, axis in (("map_x_page", x_axis), ("map_y_page", y_axis)):
            if axis["page"] > 1:
                axis["previous_url"] = url(**{key: str(axis["page"] - 1)})
            if axis["page"] < axis["page_count"]:
                axis["next_url"] = url(**{key: str(axis["page"] + 1)})
        rows = []
        for y_value in y_axis["values"]:
            row_key = _token("row", x_name, y_name, unit_token, y_value["key"])
            row = {**y_value, "key": row_key, "selected": state.get("map_row") == row_key,
                   "url": url(map_row=row_key, map_cell=None, members_page=None, edge=None) + "#study-member-browser", "cells": []}
            for x_value in x_axis["values"]:
                ids = cells.get((x_value["key"], y_value["key"]), [])
                cell_key = _token("cell", x_name, y_name, unit_token, x_value["key"], y_value["key"])
                row["cells"].append({"count": len(ids), "key": cell_key,
                                     "selected": state.get("map_cell") == cell_key,
                                     "title": f'{x_axis["label"]}: {x_value["label"]}; {y_axis["label"]}: {y_value["label"]}; {len(ids)} records',
                                     "url": url(map_cell=cell_key, map_row=None, members_page=None, edge=None) + "#study-member-browser" if ids else ""})
            rows.append(row)
        maximum = max((cell["count"] for row in rows for cell in row["cells"]), default=0)
        for row in rows:
            for cell in row["cells"]:
                cell["intensity"] = 0
                if cell["count"]:
                    cell["intensity"] = 1 + ((cell["count"] - 1) * 4 // (maximum - 1) if maximum > 1 else 0)
        for unit in sorted(unit_records, key=lambda unit: (unit.casefold(), unit)):
            token = _token("unit", unit)
            context["units"].append({"label": unit, "value": token, "selected": token == unit_token,
                                     "count": len(unit_records[unit]),
                                     "url": url(map_unit=token, map_cell=None, map_row=None,
                                                map_x_page=None, map_y_page=None, members_page=None)})
        context.update(ready=True, member_ids=member_ids, counts=counts, rows=rows, x_axis=x_axis, y_axis=y_axis,
                       max_count=maximum, selected_unit=selected_unit,
                       excluded_reasons=[{"label": label, "count": counts[name]}
                                         for name, label in EXCLUSION_LABELS.items() if counts[name]])
        context["clear_url"] = url(map_cell=None, map_row=None, members_page=None)
        context["swap_url"] = url(map_x=y_name, map_y=x_name, map_x_page=None, map_y_page=None,
                                  map_cell=None, map_row=None, members_page=None)
        context["retry_url"] = url()
    except CollectionSummaryPending as exc:
        context["preparation"] = {"ready_count": exc.ready_count, "total_count": exc.total_count,
                                  "requires_admin": exc.requires_admin}
    except ValueError as exc:
        context["error"] = str(exc)
    context["form_hidden_fields"] = [{"name": key, "value": value} for key, value in arguments.items()
                                     if key not in {"map_unit", "map_cell", "map_row", "map_x_page", "map_y_page", "members_page"}]
    return context
