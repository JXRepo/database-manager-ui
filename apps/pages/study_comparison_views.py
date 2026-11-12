"""
Export authorized recorded-metadata comparisons without changing original JSON
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .research_collections import _owned_collection, _selection_ids, _validate_access, accessible_objects
from .study_comparison import build_comparison_context, comparison_csv


def _comparison_response(request, objects, base_url):
    """
    Download only a complete authorized selection or explain preparation state

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with canonical comparison arguments.
    objects : QuerySet
        Current accessible members of the entire workspace.
    base_url : str
        Workspace location for comparison recovery.

    Returns
    -------
    HttpResponse
        A CSV snapshot or an actionable non-download response.
    """
    context = build_comparison_context(objects, request.GET, base_url=base_url)
    if context["error"]:
        response = HttpResponse(context["error"], status=400, content_type="text/plain; charset=utf-8")
    elif context["preparation"]:
        progress = context["preparation"]
        message = f'Prepared {progress["ready_count"]} of {progress["total_count"]} comparison objects. '
        message += ("Ask an administrator to prepare these records before exporting."
                    if progress["requires_admin"] else "Return to the comparison and continue preparation before exporting.")
        response = HttpResponse(message, status=503 if progress["requires_admin"] else 202,
                                content_type="text/plain; charset=utf-8")
    elif not context["ready"]:
        response = HttpResponse("Choose two to four accessible collection objects before exporting a comparison.",
                                status=400, content_type="text/plain; charset=utf-8")
    else:
        response = HttpResponse(comparison_csv(context), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="study-comparison.csv"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_GET
def collection_comparison_export(request, pk):
    """
    Export pinned accessible members of the viewer's private collection

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSV request.
    pk : int
        Collection owned by the current viewer.

    Returns
    -------
    HttpResponse
        Complete comparison snapshot or explicit validation/preparation feedback.
    """
    collection = _owned_collection(request, pk)
    objects = accessible_objects(request.user).filter(research_collections=collection)
    return _comparison_response(request, objects, reverse("collection_detail", args=[pk]))


@login_required
@require_GET
def selection_comparison_export(request, token):
    """
    Recheck the entire temporary selection before exporting its pinned subset

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSV request in the owning session.
    token : str
        Session-bound temporary selection token.

    Returns
    -------
    HttpResponse
        Complete comparison snapshot or an explicit stale-selection error.
    """
    ids = _selection_ids(request, token)
    try:
        objects = _validate_access(request.user, ids)
    except ValueError as exc:
        response = HttpResponse(str(exc), status=400, content_type="text/plain; charset=utf-8")
        response["Cache-Control"] = "private, no-store"
        return response
    return _comparison_response(request, objects, reverse("selection_detail", args=[token]))
