"""
Refresh signed study navigation after explicit presentation changes.
"""

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .collection_navigation import CONTEXT_ERROR, CONTEXT_SALT, RETURN_PARAMETERS, _return_parameters


def curve_presentation_parameters(params):
    """
    Validate optional curve presentation choices independently of curve data.

    Parameters
    ----------
    params : QueryDict or dict
        Current workspace controls.

    Returns
    -------
    dict
        Explicit open state and nondefault presentation.

    Raises
    ------
    ValueError
        A choice is repeated or unsupported.
    """
    result = {}
    for name, choices in (("curve_view", {"separate", "overlay"}), ("curve_open", {"0", "1"})):
        values = params.getlist(name) if hasattr(params, "getlist") else ([params[name]] if name in params else [])
        if len(values) > 1 or any(not isinstance(value, str) or value not in choices for value in values):
            raise ValueError("Choose one supported curve display option.")
        if values and not (name == "curve_view" and values[0] == "separate"):
            result[name] = values[0]
    return result


def _navigation_response(request, *, collection=None, selection_token=""):
    """
    Sign validated display state only for the current accessible workspace.

    This endpoint does not change saved analyses, source data or memberships.
    It avoids loading raw records when client controls update a view.

    Parameters
    ----------
    request : HttpRequest
        Authenticated GET with scalar display choices.
    collection : ResearchCollection or None, optional
        Current owned collection.
    selection_token : str, optional
        Current owner and session bound temporary selection.

    Returns
    -------
    JsonResponse
        Private signed navigation or a generic validation failure.
    """
    from .models import SavedStudyAnalysis
    from .research_collections import _selection_ids, _validate_access, accessible_objects
    from .study_comparison import parse_comparison_ids

    try:
        if set(request.GET) - RETURN_PARAMETERS or len(request.GET.urlencode().encode()) > 16384:
            raise ValueError(CONTEXT_ERROR)
        if any(len(request.GET.getlist(key)) != 1 for key in request.GET):
            raise ValueError(CONTEXT_ERROR)
        state = _return_parameters(request.GET.dict())
        selected = parse_comparison_ids(state)
        if collection is not None:
            objects = accessible_objects(request.user).filter(research_collections=collection)
            if "analysis" in state and not SavedStudyAnalysis.objects.filter(
                collection=collection, pk=state["analysis"],
            ).exists():
                raise ValueError(CONTEXT_ERROR)
        else:
            ids = _selection_ids(request, selection_token)
            objects = _validate_access(request.user, ids)
            if "analysis" in state:
                raise ValueError(CONTEXT_ERROR)
        if set(objects.filter(pk__in=selected).values_list("pk", flat=True)) != set(selected):
            raise ValueError(CONTEXT_ERROR)
        payload = {"user": request.user.pk, "kind": "collection" if collection is not None else "selection",
                   "target": collection.pk if collection is not None else selection_token, "params": state}
        token = signing.dumps(payload, salt=CONTEXT_SALT, compress=True)
        variants = {}
        for view in ("compact", "detailed"):
            variants[view] = signing.dumps({**payload, "params": {**state, "view": view}}, salt=CONTEXT_SALT, compress=True)
        return JsonResponse({"state": state, "graph_context": token, "variants": variants})
    except (ValueError, Http404, TypeError):
        return JsonResponse({"error": CONTEXT_ERROR}, status=400)


@login_required
@require_GET
@never_cache
def collection_study_navigation(request, pk):
    """
    Refresh return links within one private collection.

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    pk : int
        Collection identifier.

    Returns
    -------
    JsonResponse
        Validated signed presentation state.
    """
    from .research_collections import _owned_collection

    return _navigation_response(request, collection=_owned_collection(request, pk))


@login_required
@require_GET
@never_cache
def selection_study_navigation(request, token):
    """
    Refresh return links within one temporary selection.

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    token : str
        Session selection identifier.

    Returns
    -------
    JsonResponse
        Validated signed presentation state.
    """
    return _navigation_response(request, selection_token=token)
