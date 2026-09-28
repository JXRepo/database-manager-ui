"""
Render a shared statistical scope and its accessible data objects
"""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.pages.models import JSONData
from .analytics import (
    CATEGORY_TITLES, MEASURES, NOTE_DETAILS, RESULT_TITLES, category_rows,
    distribution, format_number, in_bin, number, summarize_object,
)

SCOPES = {"all": "All accessible", "mine": "My uploads", "public": "Public", "shared": "Shared with me"}
MULTIPLE_FILTERS = (*CATEGORY_TITLES, "result", "note", "range")
FILTER_KEYS = (*MULTIPLE_FILTERS, "measure", "lo", "hi", "inclusive")


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
    return chart_url(query, {**changes, key: selected}, objects=True)


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
    keys = ("scope", *FILTER_KEYS, "page", "show")
    query = {}
    errors = []
    for key in keys:
        if key not in params:
            continue
        values = [value.strip() for value in params.getlist(key)]
        if key in MULTIPLE_FILTERS:
            query[key] = list(dict.fromkeys(value for value in values if value or key == "range"))
        else:
            query[key] = values[0]
        if key not in MULTIPLE_FILTERS and len(values) > 1:
            errors.append(f"Choose one value for {key.replace('_', ' ')}.")
    if query.get("scope", "all") not in SCOPES:
        errors.append("Choose an available data scope.")
    if any(value not in RESULT_TITLES for value in query.get("result", [])):
        errors.append("Choose an available result type.")
    if any(value not in NOTE_DETAILS for value in query.get("note", [])):
        errors.append("Choose an available data note.")
    if query.get("measure") and query["measure"] not in MEASURES:
        errors.append("Choose temperature, grain number or discretization count.")
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
    scope = query.get("scope", "all")
    objects = JSONData.objects.filter(
        Q(owner=request.user) | Q(access_type="all") | Q(shared_users=request.user, access_type="c")
    ).distinct()
    if scope == "mine":
        objects = objects.filter(owner=request.user)
    elif scope == "public":
        objects = objects.filter(access_type="all")
    elif scope == "shared":
        objects = objects.filter(shared_users=request.user, access_type="c").exclude(owner=request.user)
    records = []
    base_count = 0
    if not errors:
        for obj in objects.only("pk", "data", "access_type").order_by("-uploaded_at", "-pk").iterator(chunk_size=1):
            base_count += 1
            record = summarize_object(obj)
            if matches_filters(record, query, intervals):
                records.append(record)
            del obj
    total = len(records)
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
    for key, title in {**CATEGORY_TITLES, "result": "Results", "note": "Data note"}.items():
        for index, selected in enumerate(query.get(key, [])):
            value = selected
            if key == "result":
                value = RESULT_TITLES.get(value, value)
            if key == "note":
                value = NOTE_DETAILS.get(value, (value, ""))[0]
            remaining = query[key][:index] + query[key][index + 1:]
            active_filters.append({"label": f"{title}: {value}", "url": chart_url(query, {key: remaining})})
    for index, measure, low, high, inclusive in intervals:
        title, unit, _observation = MEASURES[measure]
        value = format_number(low, 18) if low == high else f"{format_number(low, 18)} – {'< ' if not inclusive else ''}{format_number(high, 18)}"
        active_filters.append({"label": f"{title}: {value} {unit}".strip(),
                               "url": chart_url(query, {"range": query["range"][:index] + query["range"][index + 1:]})})
    page = Paginator(records, 10).get_page(query.get("page"))
    clear_url = chart_url({"scope": scope if scope in SCOPES else "all"})
    context = {
        "segment": "charts", "scope": scope, "scope_label": SCOPES.get(scope, "All accessible"),
        "scope_options": SCOPES.items(), "base_count": base_count, "total_objects": total,
        "phase_count": len(categories["phase"]["rows"]),
        "paired_count": sum("paired" in record["results"] for record in records),
        "plastic_count": sum("plastic_strain" in record["results"] for record in records),
        "paired_url": refine_url(query, "result", "paired"),
        "plastic_url": refine_url(query, "result", "plastic_strain"),
        "categories": categories, "distributions": distributions,
        "active_measure": query.get("measure", "temperature"), "result_rows": result_rows,
        "note_rows": note_rows, "noted_objects": sum(bool(record["notes"]) for record in records),
        "active_filters": active_filters, "filter_errors": errors, "clear_url": clear_url,
        "objects_page": page, "objects_url": chart_url(query, objects=True),
        "objects_open": bool(active_filters or query.get("show") == "objects"),
        "previous_url": chart_url(query, {"page": page.previous_page_number()}, objects=True) if page.has_previous() else "",
        "next_url": chart_url(query, {"page": page.next_page_number()}, objects=True) if page.has_next() else "",
    }
    return render(request, "charts/index.html", context)
