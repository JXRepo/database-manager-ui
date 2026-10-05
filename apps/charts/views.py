"""
Render a shared statistical scope and its accessible data objects
"""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.pages.models import JSONData
from .analytics import (
    CATEGORY_TITLES, COVERAGE_TITLES, MEASURES, NOTE_DETAILS, RESULT_TITLES, category_rows,
    distribution, format_number, in_bin, number, summarize_object,
)
from .plots import bar_plot, histogram_plot, pie_plot
from .filters import build_filter_fields

SCOPES = {"public": "Public database", "mine": "My data"}
LEGACY_SCOPES = {"all", "shared"}
MULTIPLE_FILTERS = (*CATEGORY_TITLES, "result", "note", "range", "coverage")
FILTER_KEYS = (*MULTIPLE_FILTERS, "measure", "lo", "hi", "inclusive")
MATERIAL_GROUPS = ("phase", "texture")
SETUP_GROUPS = ("software", "plastic_model", "elastic_model", "loading_type", "loading_mode")
VIEW_KEYS = ("material_group", "group", "curve", "component")


def chart_url(query, changes=None, objects=False):
    """
    Preserve the active scope when selecting a chart or changing a page

    Parameters
    ----------
    query : dict
        Known GET parameters.
    changes : dict, optional
        Values to replace, or None to remove.
    objects : bool, optional
        Expand and target the matching-object list.

    Returns
    -------
    str
        Local Charts URL with encoded values.
    """
    values = {key: value for key, value in query.items() if key != "page" and value != ""}
    for key, value in (changes or {}).items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    if objects:
        values["show"] = "objects"
    suffix = urlencode(values, doseq=True)
    return reverse("charts") + (f"?{suffix}" if suffix else "") + ("#objects" if objects else "")


def refine_url(query, key, value, **changes):
    """
    Add a condition without replacing the selection used to count its bar

    Parameters
    ----------
    query : dict
        Current scope and validated conditions.
    key : str
        Repeatable filter name.
    value : str
        Additional required value.
    **changes : str
        View preferences such as the visible numeric measure.

    Returns
    -------
    str
        Link to objects satisfying both the current and new conditions.
    """
    selected = query.get(key, [])
    if value.casefold() not in {item.casefold() for item in selected}:
        selected = [*selected, value]
    return chart_url(query, {"curve": None, "component": None, **changes, key: selected}, objects=True)


def parse_filters(params):
    """
    Validate every active selector before filtering statistical records

    Parameters
    ----------
    params : QueryDict
        Incoming GET arguments.

    Returns
    -------
    tuple
        Known parameters, errors and required numeric intervals.
    """
    keys = ("scope", "include_private", *FILTER_KEYS, *VIEW_KEYS, "page", "show")
    query = {}
    errors = []
    for key in keys:
        if key not in params:
            continue
        values = [value.strip() for value in params.getlist(key)]
        if key in MULTIPLE_FILTERS:
            query[key] = list(dict.fromkeys(value for value in values if value or key in {"range", "coverage"}))
        else:
            query[key] = values[0]
        if key not in MULTIPLE_FILTERS and len(values) > 1:
            errors.append(f"Choose one value for {key.replace('_', ' ')}.")
    if query.get("scope", "public") not in {*SCOPES, *LEGACY_SCOPES}:
        errors.append("Choose an available data scope.")
    if "include_private" in query and query["include_private"] not in {"0", "1"}:
        errors.append("Choose whether to include private data using 0 or 1.")
    if any(value not in COVERAGE_TITLES for value in query.get("coverage", [])):
        errors.append("Choose an available stress–strain coverage category.")
    if any(value not in RESULT_TITLES for value in query.get("result", [])):
        errors.append("Choose an available result type.")
    if any(value not in NOTE_DETAILS for value in query.get("note", [])):
        errors.append("Choose an available data note.")
    if query.get("measure") and query["measure"] not in MEASURES:
        errors.append("Choose temperature, grain number or discretization count.")
    if query.get("group") and query["group"] not in CATEGORY_TITLES:
        errors.append("Choose an available category.")
    if query.get("material_group") and query["material_group"] not in MATERIAL_GROUPS:
        errors.append("Choose phase or texture for materials and microstructure.")
    if query.get("component") and query["component"] not in {"equivalent", "11", "22", "33", "12", "13", "23"}:
        errors.append("Choose an available response component.")
    if query.get("curve") and (len(query["curve"]) > 20 or not query["curve"].isascii()
                              or not query["curve"].isdigit() or int(query["curve"]) < 1):
        errors.append("Choose a data object from this selection.")
    ranges = query.get("range", [])
    if any(key in query for key in ("lo", "hi", "inclusive")):
        ranges.append(":".join([query.get("measure", ""), query.pop("lo", ""),
                               query.pop("hi", ""), query.pop("inclusive", "1")]))
    intervals = []
    for index, value in enumerate(ranges):
        parts = value.split(":")
        if len(parts) != 4:
            errors.append("Choose a valid numeric interval from a distribution.")
            continue
        measure, low, high, inclusive = parts
        low, high = number(low), number(high)
        if (measure not in MEASURES or low is None or high is None
                or low < 0 or high < low or inclusive not in {"0", "1"}):
            errors.append("Choose a valid numeric interval from a distribution.")
        else:
            intervals.append((index, measure, low, high, inclusive == "1"))
    if ranges:
        query["range"] = ranges
    return query, list(dict.fromkeys(errors)), intervals


def matches_filters(record, query, intervals):
    """
    Require every active condition to match the same accessible record

    Parameters
    ----------
    record : dict
        Compact object summary.
    query : dict
        Validated filters.
    intervals : list of tuple
        Required numeric measures and bounds.

    Returns
    -------
    bool
        Whether the object belongs to the selected statistical scope.
    """
    for key in CATEGORY_TITLES:
        selected = {value.casefold() for value in query.get(key, [])}
        if not selected.issubset({value.casefold() for value in record["categories"][key]}):
            return False
    if not set(query.get("result", [])).issubset(record["results"]):
        return False
    if not set(query.get("note", [])).issubset(record["notes"]):
        return False
    matching = bool(record["curve_components"])
    for selected in query.get("coverage", []):
        if matching != (selected == "matching"):
            return False
    for _index, measure, low, high, inclusive in intervals:
        if not any(in_bin(value, low, high, inclusive) for value in record["numeric"][measure]):
            return False
    return True


@never_cache
@login_required
def index(request):
    """
    Display trustworthy statistics and matching objects under the same permissions

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with optional chart selections.

    Returns
    -------
    HttpResponse
        Rendered statistical workspace with ordinary GET navigation.
    """
    query, errors, intervals = parse_filters(request.GET)
    if not errors and query.get("scope") in LEGACY_SCOPES:
        return redirect(chart_url(query, {"scope": "public", "include_private": None}))
    group = query.get("group") or "software"
    if group in MATERIAL_GROUPS:
        query.setdefault("material_group", group)
        group = query["group"] = "software"
    material_group = query.get("material_group") or "phase"
    scope = query.get("scope", "public")
    include_private = scope == "mine" and query.get("include_private") == "1"
    if scope == "public" and not errors:
        query.pop("include_private", None)
    objects = JSONData.objects.all()
    if scope == "mine":
        objects = objects.filter(owner=request.user)
        if not include_private:
            objects = objects.filter(access_type="all")
    else:
        objects = objects.filter(access_type="all")
    records = []
    scope_records = []
    base_count = 0
    if not errors:
        for obj in objects.only("pk", "data", "access_type").order_by("-uploaded_at", "-pk").iterator(chunk_size=1):
            base_count += 1
            record = summarize_object(obj)
            scope_records.append(record)
            if matches_filters(record, query, intervals):
                records.append(record)
            del obj
    total = len(records)
    coverage_rows = []
    for key, label in COVERAGE_TITLES.items():
        count = sum(bool(record["curve_components"]) == (key == "matching") for record in records)
        coverage_rows.append({"key": key, "label": label, "count": count,
                              "color": "#2874c6" if key == "matching" else "#d9e3ee",
                              "percent": round(count * 100 / total, 1) if total else 0,
                              "url": refine_url(query, "coverage", key)})
    categories = {}
    for key in CATEGORY_TITLES:
        category = category_rows(records, key)
        for row in category["rows"]:
            row["url"] = refine_url(query, key, row["label"])
        categories[key] = category
    distributions = []
    for measure in MEASURES:
        item = distribution(records, measure)
        for bucket in item["bins"]:
            bounds = ":".join([measure, bucket["low"], bucket["high"], "1" if bucket["inclusive"] else "0"])
            bucket["url"] = refine_url(query, "range", bounds, measure=measure)
        distributions.append(item)
    result_rows = []
    for key, title in RESULT_TITLES.items():
        if key == "paired":
            continue
        count = sum(key in record["results"] for record in records)
        result_rows.append({"key": key, "title": title, "count": count,
                            "percent": round(count * 100 / total, 1) if total else 0,
                            "url": refine_url(query, "result", key)})
    note_rows = []
    for key, (title, description) in NOTE_DETAILS.items():
        count = sum(key in record["notes"] for record in records)
        if count:
            note_rows.append({"key": key, "title": title, "description": description, "count": count,
                              "url": refine_url(query, "note", key)})
    active_filters = []
    for key, title in {**CATEGORY_TITLES, "result": "Results", "note": "Data note", "coverage": "Coverage"}.items():
        for index, selected in enumerate(query.get(key, [])):
            value = selected
            if key == "result":
                value = RESULT_TITLES.get(value, value)
            if key == "note":
                value = NOTE_DETAILS.get(value, (value, ""))[0]
            if key == "coverage":
                value = COVERAGE_TITLES.get(value, value)
            remaining = query[key][:index] + query[key][index + 1:]
            active_filters.append({"label": f"{title}: {value}", "url": chart_url(query, {key: remaining})})
    for index, measure, low, high, inclusive in intervals:
        title, unit, _observation = MEASURES[measure]
        value = format_number(low, 18) if low == high else f"{format_number(low, 18)} – {'< ' if not inclusive else ''}{format_number(high, 18)}"
        active_filters.append({"label": f"{title}: {value} {unit}".strip(),
                               "url": chart_url(query, {"range": query["range"][:index] + query["range"][index + 1:]})})
    page = Paginator(records, 10).get_page(query.get("page"))
    clear_params = {"scope": scope if scope in SCOPES else "public"}
    if include_private:
        clear_params["include_private"] = "1"
    clear_url = chart_url(clear_params)
    selected_category = categories.get(group, categories["software"])
    material_category = categories.get(material_group, categories["phase"])
    measure = query.get("measure") or "temperature"
    selected_distribution = next((item for item in distributions if item["key"] == measure), distributions[0])
    controls = {}
    for name in ("material_group", "group", "measure"):
        excluded = {name, "curve", "component", "show", "page"}
        controls[name] = [(key, value) for key, values in query.items() if key not in excluded
                          for value in (values if isinstance(values, list) else [values])]
    controls["scope"] = [(key, value) for key in ("material_group", "group", "measure")
                         if (value := query.get(key))]
    filter_fields = build_filter_fields(scope_records, query)
    excluded = {*CATEGORY_TITLES, "coverage", "result", "note", "range", "page", "show"}
    controls["filters"] = [(key, value) for key, values in query.items() if key not in excluded
                           for value in (values if isinstance(values, list) else [values])]
    controls["filters"].extend(("range", value) for value in query.get("range", [])
                              if value.partition(":")[0] not in MEASURES)
    context = {
        "segment": "charts", "scope": scope, "scope_label": SCOPES.get(scope, "Public database"),
        "include_private": include_private,
        "scope_options": SCOPES.items(), "base_count": base_count, "total_objects": total,
        "phase_count": len(categories["phase"]["rows"]),
        "matching_count": sum("matching_response" in record["results"] for record in records),
        "plastic_count": sum("plastic_strain" in record["results"] for record in records),
        "matching_url": refine_url(query, "result", "matching_response"),
        "plastic_url": refine_url(query, "result", "plastic_strain"),
        "categories": categories, "distributions": distributions,
        "coverage_rows": coverage_rows, "coverage_plot": pie_plot(coverage_rows),
        "active_measure": query.get("measure", "temperature"), "result_rows": result_rows,
        "output_rows": [row for row in result_rows if row["key"] != "matching_response"],
        "note_rows": note_rows, "noted_objects": sum(bool(record["notes"]) for record in records),
        "active_filters": active_filters, "filter_errors": errors, "clear_url": clear_url,
        "objects_page": page,
        "objects_open": bool(active_filters or query.get("show") == "objects"),
        "previous_url": chart_url(query, {"page": page.previous_page_number()}, objects=True) if page.has_previous() else "",
        "next_url": chart_url(query, {"page": page.next_page_number()}, objects=True) if page.has_next() else "",
        "material_options": [(key, CATEGORY_TITLES[key]) for key in MATERIAL_GROUPS],
        "material_group": material_group, "material_category": material_category,
        "material_plot": bar_plot(material_category["rows"]),
        "group_options": [(key, CATEGORY_TITLES[key]) for key in SETUP_GROUPS],
        "selected_category": selected_category,
        "category_plot": bar_plot(selected_category["rows"]), "group": group,
        "selected_distribution": selected_distribution, "histogram": histogram_plot(selected_distribution),
        "control_params": controls,
        "filter_fields": filter_fields, "primary_filters": filter_fields[:3], "more_filters": filter_fields[3:],
        "more_filter_count": sum(field["selected_count"] for field in filter_fields[3:]),
    }
    return render(request, "charts/index.html", context)
