"""
Filter bounded parameter rows and preserve exact field focus in native navigation.
"""

import re
from urllib.parse import urlencode


DETAIL_PARAMETERS = {"detail_status", "detail_q", "detail_focus"}
DETAIL_STATUSES = (("all", "All fields"), ("different", "Differences"), ("incomplete", "Incomplete"))


def detail_parameters(params):
    """
    Validate the scalar controls used by detailed field inspection.

    Default values are omitted so saved analyses and signed links use the same
    compact representation as ordinary GET forms.

    Parameters
    ----------
    params : QueryDict or dict
        Query arguments or previously validated workspace state.

    Returns
    -------
    dict
        Nondefault search, status and field focus controls.

    Raises
    ------
    ValueError
        A control is repeated, malformed or beyond the search length limit.
    """
    values = {}
    for name in DETAIL_PARAMETERS:
        items = params.getlist(name) if hasattr(params, "getlist") else ([params[name]] if name in params else [])
        if len(items) > 1 or any(not isinstance(item, str) for item in items):
            raise ValueError("Choose each detailed parameter option once.")
        if items:
            values[name] = items[0]
    status = values.get("detail_status", "all")
    if status not in {name for name, _ in DETAIL_STATUSES}:
        raise ValueError("Choose All fields, Differences or Incomplete for detailed parameters.")
    query = values.get("detail_q", "").strip()
    if len(query) > 200:
        raise ValueError("Use at most 200 characters to find a parameter field.")
    focus = values.get("detail_focus", "")
    if "detail_focus" in values and not re.fullmatch(r"[0-9a-f]{24}", focus):
        raise ValueError("Choose a current detailed parameter field.")
    result = {}
    if status != "all":
        result["detail_status"] = status
    if query:
        result["detail_q"] = query
    if focus:
        result["detail_focus"] = focus
    return result


def apply_detail_navigation(context, params, *, base_url, navigation_params):
    """
    Decorate inspected rows with native filters and stable field destinations.

    All authorized bounded rows remain available for immediate browser filtering.
    Overall inspection counts and omission messages are not changed by filtering.

    Parameters
    ----------
    context : dict
        Completed bounded inspection receiving presentation fields.
    params : QueryDict or dict
        Current field navigation controls.
    base_url : str
        Current collection or temporary selection workspace path.
    navigation_params : dict
        Validated workspace arguments to preserve through native forms.

    Returns
    -------
    dict
        The supplied context, including row visibility and navigation controls.
    """
    state = detail_parameters(params)
    rows = context.get("rows", [])
    requested_focus = state.get("detail_focus")
    focused = next((row for row in rows if row["key"] == state.get("detail_focus")), None)
    if focused:
        state.pop("detail_status", None)
        state.pop("detail_q", None)
    elif requested_focus:
        state.pop("detail_focus", None)
    arguments = {key: value for key, value in navigation_params.items() if key not in DETAIL_PARAMETERS}
    arguments.update(state)
    arguments.update(panel="compare", inspect="1")

    def url(**changes):
        """
        Build a same-workspace field URL from validated controls.

        Parameters
        ----------
        **changes : str or None
            Explicit replacements or removals.

        Returns
        -------
        str
            Encoded native workspace destination.
        """
        values = {**arguments, **changes}
        return base_url + "?" + urlencode({key: value for key, value in values.items() if value is not None and value != ""})

    status = state.get("detail_status", "all")
    query = state.get("detail_q", "")
    terms = query.lower().split()
    groups = []
    visible_count = 0
    for row in rows:
        if not groups or groups[-1]["label"] != row["group"]:
            groups.append({"key": str(len(groups)), "label": row["group"], "visible": False, "rows": []})
        group = groups[-1]
        row["search_text"] = (row["label"] + " " + row["path"]).lower()
        row["visible"] = (status == "all" or row["status"] == status) and all(term in row["search_text"] for term in terms)
        row["group_key"] = group["key"]
        row["focused"] = row is focused
        group["rows"].append(row)
        if row["visible"]:
            visible_count += 1
            group["visible"] = True
    for difference in context.get("differences", []):
        difference["focus_url"] = url(detail_status=None, detail_q=None, detail_focus=difference["key"]) + "#" + difference["id"]
    filters = []
    for value, label in DETAIL_STATUSES:
        count = context["counts"]["total" if value == "all" else value]
        filters.append({"value": value, "label": label, "count": count, "selected": value == status,
                        "url": url(detail_status=value, detail_focus=None) + "#study-parameter-fields"})
    context["navigation"] = {
        "state": state, "status": status, "query": query, "filters": filters, "groups": groups,
        "visible_count": visible_count, "table_open": any(key in params for key in DETAIL_PARAMETERS), "form_url": base_url,
        "focus_id": focused["id"] if focused else "", "focus_missing": bool(requested_focus and not focused),
        "clear_url": url(detail_status="all", detail_q=None, detail_focus=None) + "#study-parameter-fields",
        "search_hidden_fields": [{"name": key, "value": value} for key, value in {**arguments, "detail_status": status}.items()
                                 if key not in {"detail_q", "detail_focus"}],
    }
    return context
