"""
Keep collection navigation private and limited to known workspace destinations
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.core import signing
from django.http import Http404
from django.urls import reverse


CONTEXT_SALT = "pages.collection-navigation.v1"
CONTEXT_MAX_AGE = 7 * 24 * 60 * 60
CONTEXT_ERROR = (
    "This collection or selection link is no longer available. "
    "Open Graph and choose the collection or selection again."
)
RETURN_PARAMETERS = {"links", "group", "page", "groups_page", "view", "edge", "relationships_page",
                     "compare", "panel", "member_q", "members_page", "differences",
                     "find_candidates", "match_fields", "vary_field", "candidates_page", "curve_component", "curve_strain",
                     "inspect", "map_x", "map_y", "map_unit", "map_x_page", "map_y_page", "map_cell", "map_row"}


def _return_parameters(values):
    """
    Accept only bounded collection display arguments

    Parameters
    ----------
    values : dict
        Signed display arguments without a destination URL.

    Returns
    -------
    dict
        Validated scalar arguments for the original workspace.

    Raises
    ------
    ValueError
        An argument is unknown, repeated or invalid.
    """
    if not isinstance(values, dict) or set(values) - RETURN_PARAMETERS:
        raise ValueError(CONTEXT_ERROR)
    params = {}
    for key, value in values.items():
        if not isinstance(value, str):
            raise ValueError(CONTEXT_ERROR)
        if key == "links" and value not in {"relations", "software", "phase", "members"}:
            raise ValueError(CONTEXT_ERROR)
        if key == "view" and value not in {"compact", "detailed"}:
            raise ValueError(CONTEXT_ERROR)
        if key == "group" and not re.fullmatch(r"[0-9a-f]{24}|missing", value):
            raise ValueError(CONTEXT_ERROR)
        if key in {"page", "groups_page", "relationships_page"} and (
            not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > 2147483647
        ):
            raise ValueError(CONTEXT_ERROR)
        if key == "edge" and (
            not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 9223372036854775807
        ):
            raise ValueError(CONTEXT_ERROR)
        params[key] = value
    if params.get("links") == "members" and "group" in params:
        raise ValueError(CONTEXT_ERROR)
    if any(key in params for key in ("compare", "panel", "member_q", "members_page", "differences",
                                    "find_candidates", "match_fields", "vary_field", "candidates_page",
                                    "curve_component", "curve_strain", "inspect", "map_x", "map_y", "map_unit",
                                    "map_x_page", "map_y_page", "map_cell", "map_row")):
        from .study_workspace import study_parameters

        try:
            study_parameters(params)
        except ValueError:
            raise ValueError(CONTEXT_ERROR) from None
    return params


def with_graph_context(url, token):
    """
    Carry a validated context through a local link while preserving its fragment

    Parameters
    ----------
    url : str
        Existing application link.
    token : str
        Validated context token, or an empty value to remove a stale token.

    Returns
    -------
    str
        Link with exactly one context argument when supplied.
    """
    parts = urlsplit(url)
    params = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
              if key != "graph_context"]
    if token:
        params.append(("graph_context", token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def read_navigation(request, *, data=None):
    """
    Resolve a signed workspace after checking the current user and session

    Temporary selections also require all their original objects to remain
    accessible before they can be extended.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request holding the current session.
    data : QueryDict or None, optional
        Token source, defaulting to GET arguments.

    Returns
    -------
    dict or None
        Validated target, display arguments and token, or no supplied context.

    Raises
    ------
    ValueError
        The token, owner, session or original selection is no longer valid.
    """
    from .research_collections import _owned_collection, _selection_ids, _validate_access

    data = request.GET if data is None else data
    values = data.getlist("graph_context")
    if not values:
        return None
    if len(values) != 1 or not values[0] or len(values[0]) > 4096:
        raise ValueError(CONTEXT_ERROR)
    token = values[0]
    try:
        payload = signing.loads(token, salt=CONTEXT_SALT, max_age=CONTEXT_MAX_AGE)
        if not isinstance(payload, dict) or set(payload) != {"user", "kind", "target", "params"}:
            raise ValueError(CONTEXT_ERROR)
        if type(payload["user"]) is not int or payload["user"] != request.user.pk:
            raise ValueError(CONTEXT_ERROR)
        params = _return_parameters(payload["params"])
        navigation = {"token": token, "params": params, "kind": payload["kind"]}
        if payload["kind"] == "collection":
            if type(payload["target"]) is not int or not 0 < payload["target"] <= 9223372036854775807:
                raise ValueError(CONTEXT_ERROR)
            navigation["collection"] = _owned_collection(request, payload["target"])
        elif payload["kind"] == "selection":
            if not isinstance(payload["target"], str):
                raise ValueError(CONTEXT_ERROR)
            ids = _selection_ids(request, payload["target"])
            _validate_access(request.user, ids)
            navigation.update(selection_token=payload["target"], ids=ids)
        else:
            raise ValueError(CONTEXT_ERROR)
    except (signing.BadSignature, Http404, TypeError, KeyError):
        raise ValueError(CONTEXT_ERROR) from None
    return navigation


def navigation_fields(navigation):
    """
    Describe an owned workspace without accepting a caller supplied return URL

    Parameters
    ----------
    navigation : dict or None
        Previously validated context.

    Returns
    -------
    dict
        Public template fields for returning and selecting more data.
    """
    fields = {
        "graph_context": "", "graph_return_url": "", "graph_return_label": "",
        "graph_add_label": "", "graph_continue_search_url": "",
        "graph_continue_my_data_url": "", "graph_navigation_error": "",
    }
    if navigation is None:
        return fields
    collection = navigation.get("collection")
    if collection is not None:
        url = reverse("collection_detail", args=[collection.pk])
        label = f"Back to {collection.title}"
        add_label = f"Add to {collection.title}"
    else:
        url = reverse("selection_detail", args=[navigation["selection_token"]])
        label = "Back to selection"
        add_label = "Add to this selection"
    if navigation["params"]:
        url += "?" + urlencode(navigation["params"])
    return {
        **fields, "graph_context": navigation["token"], "graph_return_url": url,
        "graph_return_label": label, "graph_add_label": add_label,
        "graph_continue_search_url": with_graph_context(reverse("search"), navigation["token"]),
        "graph_continue_my_data_url": with_graph_context(reverse("json_data_list"), navigation["token"]),
    }


def read_mutation_navigation(request, *, collection=None, selection_token=""):
    """
    Accept optional signed POST state only for the exact workspace being changed

    Parameters
    ----------
    request : HttpRequest
        Authenticated mutation request with optional graph_context form field.
    collection : ResearchCollection or None, optional
        Already owned collection whose mutation is requested.
    selection_token : str, optional
        Session selection being saved when no collection is supplied.

    Returns
    -------
    dict or None
        Validated navigation state, or no state for legacy native submissions.

    Raises
    ------
    ValueError
        Navigation is ambiguous, unsigned, repeated or names a different workspace.
    """
    if any(key in request.GET for key in RETURN_PARAMETERS | {"graph_context", "match_field"}):
        raise ValueError(CONTEXT_ERROR)
    if any(key in request.POST for key in RETURN_PARAMETERS | {"match_field"}):
        raise ValueError(CONTEXT_ERROR)
    navigation = read_navigation(request, data=request.POST)
    if navigation is None:
        return None
    if collection is not None:
        if navigation["kind"] != "collection" or navigation["collection"].pk != collection.pk:
            raise ValueError(CONTEXT_ERROR)
    elif navigation["kind"] != "selection" or navigation["selection_token"] != selection_token:
        raise ValueError(CONTEXT_ERROR)
    return navigation


def navigation_context(request):
    """
    Show optional return navigation without denying access to an accessible object

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with optional GET context.

    Returns
    -------
    dict
        Valid navigation or a generic error without a private collection title.
    """
    try:
        return navigation_fields(read_navigation(request))
    except ValueError as exc:
        return {**navigation_fields(None), "graph_navigation_error": str(exc)}


def workspace_navigation(request, context, *, collection=None, selection_token=""):
    """
    Sign the displayed workspace scope and attach it to object navigation

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    context : dict
        Completed graph context with canonical group and page values.
    collection : ResearchCollection or None, optional
        Already owned collection, when saved.
    selection_token : str, optional
        Current session selection, when unsaved.

    Returns
    -------
    dict
        Navigation fields; member rows and record nodes gain contextual links.
    """
    from .research_collections import _selection_ids, _validate_access

    params = {"links": context["links_mode"], "view": context["graph_view_mode"]}
    for field, key in (("object_page", "page"), ("group_page", "groups_page")):
        params[key] = str(context[field].number)
    if context.get("selected_group"):
        params["group"] = context["selected_group"]["key"]
    if context.get("manual_selected"):
        params["edge"] = str(context["manual_selected"]["id"])
    if context.get("manual_editor") and context["manual_editor"]["page"].number > 1:
        params["relationships_page"] = str(context["manual_editor"]["page"].number)
    params.update(context.get("study_return_params", {}))
    params = _return_parameters(params)
    payload = {
        "user": request.user.pk, "kind": "collection" if collection is not None else "selection",
        "target": collection.pk if collection is not None else selection_token, "params": params,
    }
    if collection is None:
        try:
            _validate_access(request.user, _selection_ids(request, selection_token))
        except ValueError as exc:
            return {**navigation_fields(None), "graph_navigation_error": str(exc)}
    token = signing.dumps(payload, salt=CONTEXT_SALT)
    navigation = {**payload, "token": token, "collection": collection, "selection_token": selection_token}
    fields = navigation_fields(navigation)
    for view in ("compact", "detailed"):
        fields[f"graph_context_{view}"] = signing.dumps(
            {**payload, "params": {**params, "view": view}}, salt=CONTEXT_SALT,
        )
    candidates = context.get("study_candidates", {})
    source_rows = [*context.get("object_rows", []), *context.get("study_comparison", {}).get("objects", []),
                   *candidates.get("rows", []), *candidates.get("uncertain_rows", [])]
    if candidates.get("reference"):
        source_rows.append(candidates["reference"])
    for row in source_rows:
        row["detail_url"] = with_graph_context(row["detail_url"], token)
        row["graph_url"] = with_graph_context(row["graph_url"], token)
        row["metadata_url"] = row["detail_url"] + "#data-metadata"
        row["curves_url"] = row["detail_url"] + "#data-curves"
    for row in context.get("study_workspace", {}).get("browser_rows", []):
        row["show_url"] = with_graph_context(row["show_url"], token)
    for row in context.get("study_details", {}).get("objects", []):
        row["detail_url"] = with_graph_context(row["detail_url"], token)
    for node in (context.get("relationship_graph") or {}).get("nodes", []):
        if node.get("id", "").startswith("collection-object-"):
            for key in ("source_url", "graph_url"):
                if node.get(key):
                    node[key] = with_graph_context(node[key], token)
    return fields
