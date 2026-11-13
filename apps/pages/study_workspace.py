"""
Carry bounded study selections through native browsing and graph navigation
"""

import re
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.urls import reverse

from .advanced_search import matches_whole_words


STUDY_PARAMETERS = {"compare", "panel", "member_q", "members_page", "differences",
                    "find_candidates", "match_fields", "vary_field", "candidates_page",
                    "curve_component", "curve_strain"}


def study_parameters(params):
    """
    Validate the scalar study controls before placing them in navigation links

    Parameters
    ----------
    params : QueryDict or dict
        Workspace query arguments or previously signed return arguments.

    Returns
    -------
    dict
        Canonical study arguments without empty or default values.

    Raises
    ------
    ValueError
        A control is repeated, malformed or exceeds its bound.
    """
    from .study_comparison import parse_comparison_ids
    from .study_candidates import candidate_parameters
    from .study_curves import curve_parameters

    values = {}
    for name in STUDY_PARAMETERS:
        items = params.getlist(name) if hasattr(params, "getlist") else ([params[name]] if name in params else [])
        if len(items) > 1 or any(not isinstance(item, str) for item in items):
            raise ValueError("Choose each study option once.")
        if items:
            values[name] = items[0]
    ids = parse_comparison_ids(params)
    panel = values.get("panel", "explore")
    if panel not in {"explore", "compare"}:
        raise ValueError("Choose Explore or Compare for this study.")
    differences = values.get("differences", "0")
    if differences not in {"0", "1"}:
        raise ValueError("Choose a valid comparison display.")
    query = values.get("member_q", "").strip()
    if len(query) > 200:
        raise ValueError("Use at most 200 characters to find study records.")
    page = values.get("members_page", "1")
    if not re.fullmatch(r"[1-9][0-9]{0,9}", page) or int(page) > 2147483647:
        raise ValueError("Choose a valid page of study records.")
    result = {}
    if ids:
        result["compare"] = ",".join(map(str, ids))
    if panel == "compare":
        result["panel"] = panel
    if query:
        result["member_q"] = query
    if page != "1":
        result["members_page"] = page
    if differences == "1":
        result["differences"] = differences
    result.update(candidate_parameters(params))
    curves = curve_parameters(params)
    for key in ("curve_component", "curve_strain"):
        if key in params:
            result[key] = curves[key]
    return result


def build_study_workspace_context(objects, context, params, *, base_url, collection=None, selection_token="",
                                  preparation_budget=None):
    """
    Assemble a comparison and searchable member browser from accessible summaries

    Parameters
    ----------
    objects : QuerySet
        Current collection or temporary selection after applying access rules.
    context : dict
        Existing graph and accessible scalar member summaries.
    params : QueryDict or dict
        Current native workspace controls.
    base_url : str
        Owned collection or session selection URL.
    collection : ResearchCollection or None, optional
        Saved collection already restricted to its owner.
    selection_token : str, optional
        Current temporary selection token when unsaved.
    preparation_budget : SummaryPreparationBudget or None, optional
        Preparation allowance shared by the full workspace request.

    Returns
    -------
    dict
        Comparison, browser and validated signed-return state.
    """
    from .study_comparison import build_comparison_context
    from .study_candidates import CANDIDATE_FORM_PARAMETERS, build_candidate_context, candidate_parameters
    from .study_curves import curve_parameters

    error = ""
    controls = params
    try:
        candidate_parameters(params)
    except ValueError:
        controls = params.copy()
        for name in CANDIDATE_FORM_PARAMETERS:
            controls.pop(name, None)
    try:
        state = study_parameters(controls)
    except ValueError as exc:
        state = {"panel": "compare"} if params.get("panel") == "compare" else {}
        error = str(exc)
    comparison = build_comparison_context(objects, params, base_url=base_url, preparation_budget=preparation_budget)
    if error or comparison.get("error"):
        error = error or comparison["error"]
        comparison.update(error=error, ready=False, ids=[], objects=[], rows=[])
        state.pop("compare", None)
    ids = comparison["ids"]
    selection = ",".join(map(str, ids))
    if selection:
        state["compare"] = selection
    arguments = {"links": context["links_mode"], **state}
    if context["graph_view_mode"] == "detailed":
        arguments["view"] = "detailed"
    if context.get("selected_group"):
        arguments["group"] = context["selected_group"]["key"]
    if context.get("manual_selected"):
        arguments["edge"] = str(context["manual_selected"]["id"])
    for key, field in (("page", "object_page"), ("groups_page", "group_page")):
        if context[field].number > 1:
            arguments[key] = str(context[field].number)

    def url(**changes):
        """
        Replace explicit study controls without accepting arbitrary destinations

        Parameters
        ----------
        **changes : object
            Query values to replace or remove with None.

        Returns
        -------
        str
            Same-workspace URL with encoded scalar arguments.
        """
        values = {**arguments, **changes}
        return base_url + "?" + urlencode({key: value for key, value in values.items()
                                            if value is not None and value != ""})

    for record in comparison["objects"]:
        record["remove_url"] = url(compare=",".join(str(pk) for pk in ids if pk != record["pk"]),
                                   edge=None, candidates_page=None)
        reordered = [record["pk"], *[pk for pk in ids if pk != record["pk"]]]
        record["reference_url"] = url(compare=",".join(map(str, reordered)), edge=None, candidates_page=None)
        record["is_reference"] = record["pk"] == ids[0]
    query = state.get("member_q", "")
    members = context["manual_member_summaries"]
    matching = []
    for member in members:
        values = (member.get(key, "") for key in ("title", "identifier", "software", "phase", "creator", "loading"))
        if not matches_whole_words(values, query.split()):
            continue
        row = dict(member)
        row["selected"] = member["pk"] in ids
        row["pin_url"] = ""
        if row["selected"]:
            row["pin_url"] = url(compare=",".join(str(pk) for pk in ids if pk != row["pk"]), edge=None)
        elif len(ids) < 4:
            row["pin_url"] = url(compare=",".join(map(str, [*ids, row["pk"]])), edge=None)
        row["show_url"] = row["detail_url"]
        matching.append(row)
    browser_page = Paginator(matching if not error else [], 25).get_page(state.get("members_page", "1"))
    if browser_page.number > 1:
        state["members_page"] = str(browser_page.number)
    else:
        state.pop("members_page", None)
    arguments.pop("members_page", None)
    if "members_page" in state:
        arguments["members_page"] = state["members_page"]
    candidates = build_candidate_context(objects, comparison, params, base_url=base_url,
                                         navigation_params=arguments, preparation_budget=preparation_budget)
    if candidates["state"]:
        state.pop("candidates_page", None)
        state.update(candidates["state"])
        arguments.pop("candidates_page", None)
        arguments.update(candidates["state"])
    curves = curve_parameters(controls) if not error else {"curve_component": "equivalent", "curve_strain": "total"}
    curve_route = "collection_study_curves" if collection is not None else "selection_study_curves"
    curve_target = collection.pk if collection is not None else selection_token
    comparison.update(
        selection_value=selection,
        differences_url=url(panel="compare", differences="1"),
        all_fields_url=url(panel="compare", differences=None),
        retry_url=url(panel="compare"),
        csv_url="",
    )
    if comparison["ready"]:
        route = "collection_comparison_export" if collection is not None else "selection_comparison_export"
        target = collection.pk if collection is not None else selection_token
        comparison["csv_url"] = reverse(route, args=[target]) + "?" + urlencode({
            "compare": selection, "differences": "1" if comparison["differences"] else "0",
        })
    search_fields = [{"name": key, "value": str(value)} for key, value in arguments.items()
                     if key not in {"member_q", "members_page"}]
    return {
        "study_comparison": comparison,
        "study_candidates": candidates,
        "study_curves": {
            "url": reverse(curve_route, args=[curve_target]) + "?" + urlencode({"compare": selection, **curves}),
            "component": curves["curve_component"], "strain": curves["curve_strain"],
            "open": any(name in params for name in ("curve_component", "curve_strain")),
            "form_url": base_url,
            "hidden_fields": [{"name": key, "value": value} for key, value in arguments.items()
                              if key not in {"curve_component", "curve_strain"}],
        },
        "study_return_params": state,
        "study_workspace": {
            "panel": state.get("panel", "explore"), "error": error,
            "explore_url": url(panel="explore"), "compare_url": url(panel="compare", edge=None),
            "clear_url": url(compare=None, differences=None, edge=None, member_q=None, members_page=None,
                             find_candidates=None, match_fields=None, vary_field=None, candidates_page=None),
            "candidate_url": url(find_candidates="1", panel="explore", candidates_page=None, edge=None),
            "selection_value": selection, "selection_limit": 4,
            "browser_query": query, "browser_rows": list(browser_page.object_list),
            "browser_page": browser_page, "browser_clear_url": url(member_q=None, members_page=None),
            "previous_url": url(members_page=browser_page.previous_page_number()) if browser_page.has_previous() else "",
            "next_url": url(members_page=browser_page.next_page_number()) if browser_page.has_next() else "",
            "search_hidden_fields": search_fields, "search_url": base_url,
            "focus_count": len(ids) if len(ids) >= 2 and not context.get("manual_selected") else 0,
        },
    }
