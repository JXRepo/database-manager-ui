"""
Find collection candidates using explicit complete recorded-field comparisons
"""

import re
from urllib.parse import urlencode

from django.core.paginator import Paginator

from .collection_graph import CollectionSummaryPending, collection_summaries
from .study_comparison import COMPARISON_FIELDS, parse_comparison_ids


CANDIDATE_PARAMETERS = {"find_candidates", "match_fields", "vary_field", "candidates_page"}
CANDIDATE_FORM_PARAMETERS = CANDIDATE_PARAMETERS | {"match_field"}
CANDIDATE_FIELDS = tuple(field for field in COMPARISON_FIELDS if field[0] not in {"units", "outputs"})
FIELD_LABELS = {key: label for key, label, _ in CANDIDATE_FIELDS}
PAGE_SIZE = 25
UNCERTAIN_LIMIT = 10
UNAVAILABLE_SELECTION = "Some comparison objects are unavailable. Choose accessible records from this collection again."


def _values(params, name):
    """
    Read scalar query values without silently choosing among repeated controls

    Parameters
    ----------
    params : QueryDict or dict
        Incoming GET arguments or canonical navigation values.
    name : str
        One known parameter name.

    Returns
    -------
    list
        Submitted values in their original order.
    """
    return params.getlist(name) if hasattr(params, "getlist") else ([params[name]] if name in params else [])


def candidate_parameters(params):
    """
    Canonicalize explicit candidate criteria without treating an empty form as defaults

    Native checkboxes use match_field with one leading empty hidden sentinel.
    Canonical links and signed navigation use one comma-separated match_fields.

    Parameters
    ----------
    params : QueryDict or dict
        Incoming native controls or scalar navigation parameters.

    Returns
    -------
    dict
        Enabled criteria with one canonical field order, or no candidate state.

    Raises
    ------
    ValueError
        Controls are malformed, repeated, empty, unknown or contradictory.
    """
    if not any(name in params for name in CANDIDATE_FORM_PARAMETERS):
        return {}
    values = {}
    for name in CANDIDATE_PARAMETERS:
        items = _values(params, name)
        if len(items) > 1 or any(not isinstance(item, str) for item in items):
            raise ValueError("Choose each candidate option once.")
        if items:
            values[name] = items[0]
    if values.get("find_candidates") != "1":
        raise ValueError("Open Find comparison candidates to choose matching fields.")
    native = _values(params, "match_field")
    if native and "match_fields" in values:
        raise ValueError("Submit matching fields in one form only.")
    if any(not isinstance(item, str) for item in native):
        raise ValueError("Choose valid matching fields.")
    if "match_field" in params:
        if not native or native[0] != "":
            raise ValueError("Submit matching fields using the candidate form.")
        selected = native[1:]
    elif "match_fields" in values:
        selected = values["match_fields"].split(",")
    else:
        selected = ["software", "phase"]
    if not selected or len(selected) > len(FIELD_LABELS) or len(set(selected)) != len(selected):
        raise ValueError("Choose at least one distinct field to keep the same.")
    if any(key not in FIELD_LABELS for key in selected):
        raise ValueError("Choose valid recorded fields to keep the same.")
    vary = values.get("vary_field", "temperature")
    if vary not in FIELD_LABELS:
        raise ValueError("Choose a valid recorded field to vary.")
    if vary in selected:
        raise ValueError("The field to vary must differ from the fields kept the same.")
    page = values.get("candidates_page", "1")
    if not re.fullmatch(r"[1-9][0-9]{0,9}", page) or int(page) > 2147483647:
        raise ValueError("Choose a valid candidate page.")
    ordered = [key for key, _, _ in CANDIDATE_FIELDS if key in selected]
    result = {"find_candidates": "1", "match_fields": ",".join(ordered), "vary_field": vary}
    if page != "1":
        result["candidates_page"] = page
    return result


def _complete(cell):
    """
    Require a complete recorded fingerprint before claiming a match or difference

    Parameters
    ----------
    cell : dict
        One bounded recorded-field projection.

    Returns
    -------
    bool
        Whether every represented value was complete and unambiguous.
    """
    return cell.get("state") == "recorded" and bool(cell.get("key"))


def _evidence(reference, candidate, keys, vary):
    """
    Explain each requested condition using the two recorded values and their states

    Parameters
    ----------
    reference, candidate : dict
        Bounded field projections for the reference and candidate.
    keys : list of str
        Selected matching fields followed by the field requested to vary.
    vary : str
        Field whose recorded value must differ.

    Returns
    -------
    list of dict
        Per-field facts without a scientific comparability or similarity score.
    """
    evidence = []
    for key in keys:
        first = reference[key]
        second = candidate[key]
        status = "incomplete"
        if _complete(first) and _complete(second):
            status = "same" if first["key"] == second["key"] else "different"
        evidence.append({"key": key, "label": FIELD_LABELS[key], "expected": "different" if key == vary else "same",
                         "status": status, "reference": first, "candidate": second})
    return evidence


def build_candidate_context(objects, comparison, params, *, base_url, navigation_params=None,
                            preparation_budget=None):
    """
    Classify accessible collection members against transparent user-selected criteria

    Missing or outdated summaries are prepared within the existing request budget.
    No candidate results are returned while any accessible member still needs work.

    Parameters
    ----------
    objects : QuerySet
        Collection or temporary selection already filtered by current access rules.
    comparison : dict
        Validated comparison state whose first selected record is the reference.
    params : QueryDict or dict
        Native candidate criteria and the complete ordered comparison selection.
    base_url : str
        Known local workspace route.
    navigation_params : dict or None, optional
        Validated scalar display arguments to retain in native links.
    preparation_budget : object or None, optional
        Shared collection-summary budget for this workspace request.

    Returns
    -------
    dict
        Bounded candidate evidence, native controls, or explicit validation/preparation state.
    """
    context = {
        "enabled": any(name in params for name in CANDIDATE_FORM_PARAMETERS),
        "ready": False, "error": "", "preparation": None, "reference": None,
        "reference_missing_fields": [], "match_fields": ["software", "phase"], "vary_field": "temperature",
        "fields": [], "counts": {"matching": 0, "uncertain": 0, "excluded": 0, "total": 0},
        "rows": [], "uncertain_rows": [], "uncertain_limit": UNCERTAIN_LIMIT, "page": None,
        "previous_url": "", "next_url": "", "retry_url": "", "clear_url": base_url,
        "form_hidden_fields": [], "state": {},
    }
    arguments = {key: value for key, value in (navigation_params or {}).items()
                 if key not in CANDIDATE_FORM_PARAMETERS}
    context["form_hidden_fields"] = [{"name": key, "value": value} for key, value in arguments.items()]
    context["form_hidden_fields"].append({"name": "find_candidates", "value": "1"})

    def url(**changes):
        """
        Retain validated display state while updating one local candidate action

        Parameters
        ----------
        **changes : object
            Scalar argument replacements or None for removal.

        Returns
        -------
        str
            Encoded same-workspace URL.
        """
        values = {**arguments, **changes}
        query = urlencode({key: value for key, value in values.items() if value is not None and value != ""})
        return base_url + ("?" + query if query else "")

    context["clear_url"] = url()
    try:
        state = candidate_parameters(params)
        if not state:
            return context
        context["state"] = state
        context["match_fields"] = state["match_fields"].split(",")
        context["vary_field"] = state["vary_field"]
        ids = parse_comparison_ids(params)
        if not ids:
            raise ValueError("Pin a reference record before finding comparison candidates.")
        if comparison.get("error") or comparison.get("ids") != ids:
            raise ValueError(UNAVAILABLE_SELECTION)
        if objects.filter(pk__in=ids).count() != len(ids):
            raise ValueError(UNAVAILABLE_SELECTION)
        arguments.update(compare=",".join(map(str, ids)), **state)
        arguments.pop("edge", None)
        context["retry_url"] = url()
        context["clear_url"] = url(**{key: None for key in CANDIDATE_PARAMETERS})
        context["form_hidden_fields"] = [{"name": key, "value": value} for key, value in arguments.items()
                                         if key not in {"match_fields", "vary_field", "candidates_page"}]
        options = {"budget": preparation_budget} if preparation_budget is not None else {}
        summaries = list(collection_summaries(objects, require_comparison=True, **options))
        by_id = {row["pk"]: row for row in summaries}
        current_ids = set(objects.values_list("pk", flat=True))
        if not set(ids).issubset(current_ids):
            raise ValueError(UNAVAILABLE_SELECTION)
        if set(by_id) != current_ids:
            raise ValueError("This collection changed during the search. Refresh and find candidates again.")
        reference = by_id[ids[0]]
        context["reference"] = {key: reference[key] for key in ("pk", "title", "identifier", "detail_url", "graph_url")}
        matching_fields = context["match_fields"]
        vary = context["vary_field"]
        selected_fields = [*matching_fields, vary]
        reference_fields = reference["comparison"]["fields"]
        context["reference"]["evidence"] = _evidence(reference_fields, reference_fields, selected_fields, vary)
        context["reference_missing_fields"] = [FIELD_LABELS[key] for key in selected_fields
                                                if not _complete(reference_fields[key])]
        if context["reference_missing_fields"]:
            missing = ", ".join(context["reference_missing_fields"])
            raise ValueError(f"The reference has incomplete values for: {missing}. Choose another reference or different fields.")
        matching, uncertain = [], []
        for summary in summaries:
            if summary["pk"] == ids[0]:
                continue
            cells = summary["comparison"]["fields"]
            facts = _evidence(reference_fields, cells, selected_fields, vary)
            excluded = any(fact["status"] != "incomplete" and fact["status"] != fact["expected"] for fact in facts)
            status = "excluded" if excluded else "uncertain" if any(fact["status"] == "incomplete" for fact in facts) else "matching"
            context["counts"][status] += 1
            if status != "excluded":
                (matching if status == "matching" else uncertain).append(summary)
        context["counts"]["total"] = len(summaries) - 1
        page = Paginator(matching, PAGE_SIZE).get_page(state.get("candidates_page", "1"))
        context["page"] = page
        if page.number > 1:
            arguments["candidates_page"] = str(page.number)
            context["state"]["candidates_page"] = str(page.number)
        else:
            arguments.pop("candidates_page", None)
            context["state"].pop("candidates_page", None)
        for target, source in (("rows", page.object_list), ("uncertain_rows", uncertain[:UNCERTAIN_LIMIT])):
            for summary in source:
                row = {key: summary[key] for key in ("pk", "title", "identifier", "detail_url", "graph_url")}
                row["evidence"] = _evidence(reference_fields, summary["comparison"]["fields"], selected_fields, vary)
                row["selected"] = row["pk"] in ids
                row["compare_url"] = url(compare=f'{ids[0]},{row["pk"]}', panel="compare", edge=None)
                row["pin_url"] = (url(compare=",".join(map(str, [*ids, row["pk"]])), panel="compare", edge=None)
                                  if row["pk"] not in ids and len(ids) < 4 else "")
                context[target].append(row)
        context["previous_url"] = url(candidates_page=page.previous_page_number()) if page.has_previous() else ""
        context["next_url"] = url(candidates_page=page.next_page_number()) if page.has_next() else ""
        context["ready"] = True
    except CollectionSummaryPending as exc:
        context["preparation"] = {"ready_count": exc.ready_count, "total_count": exc.total_count,
                                  "requires_admin": exc.requires_admin}
    except ValueError as exc:
        context["error"] = str(exc)
    finally:
        context["fields"] = [{"key": key, "label": label, "group": group,
                              "selected": key in context["match_fields"], "is_vary": key == context["vary_field"]}
                             for key, label, group in CANDIDATE_FIELDS]
    return context
