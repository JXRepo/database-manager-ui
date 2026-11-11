"""
Open one accessible data object in the Graph workspace
"""

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.dyn_api.metadata_compat import field_value, metadata_view

from .advanced_search import matches_whole_words
from .detail_relationships import build_relationship_graph
from .models import JSONData
from .views import _assistant_text, _extract_plot_variables, _split_keyword_terms


def _object_option(obj):
    """
    Read a selector label without normalizing or retaining the object's arrays

    Parameters
    ----------
    obj : JSONData
        An accessible record fetched for the current selector page.

    Returns
    -------
    dict
        Local record ID, title and supplied identifier.
    """
    return {
        "pk": obj.pk,
        "title": _assistant_text(field_value(obj.data, "title")),
        "identifier": _assistant_text(field_value(obj.data, "identifier")),
    }


def _object_choices(objects, query, page_number):
    """
    Prepare one bounded selector page using the existing whole word matcher

    Only label summaries survive a search; raw JSON is released per record.
    Without a query, pagination happens in the database before reading JSON.

    Parameters
    ----------
    objects : QuerySet
        Records already restricted to the viewer's access.
    query : str
        Optional title or identifier words.
    page_number : str or None
        Requested selector page.

    Returns
    -------
    tuple
        Page metadata and its list of object summaries.
    """
    objects = objects.only("pk", "data").order_by("-uploaded_at", "-pk")
    if query:
        matches = []
        terms = _split_keyword_terms(query)
        for obj in objects.iterator(chunk_size=1):
            option = _object_option(obj)
            if matches_whole_words((option["title"], option["identifier"]), terms):
                matches.append(option)
        page = Paginator(matches, 25).get_page(page_number)
        return page, list(page.object_list)
    page = Paginator(objects, 25).get_page(page_number)
    options = []
    for obj in page.object_list.iterator(chunk_size=1):
        options.append(_object_option(obj))
    return page, options


@login_required
@require_GET
def graph_view(request):
    """
    Show a selected record's graph and an optional accessible object picker

    The workspace and selector apply the same owner, public and explicit share
    rules as detail pages. Invalid selections never fall back to another record.

    Parameters
    ----------
    request : HttpRequest
        A GET request with optional object, choose, q and page arguments.

    Returns
    -------
    HttpResponse
        Graph workspace, object chooser or a clear invalid selection response.
    """
    values = request.GET.getlist("object")
    value = values[0] if values else ""
    invalid = len(values) > 1 or bool(value and (
        not value.isascii() or not value.isdecimal() or len(value) > 19
    ))
    if not invalid and value:
        invalid = not 0 < int(value) <= 9223372036854775807
    if invalid:
        return render(request, "pages/graph.html", {
            "selection_error": "Choose one valid data object to open its graph.",
        }, status=400)

    shares = JSONData.shared_users.through.objects.filter(
        jsondata_id=OuterRef("pk"), user_id=request.user.pk,
    )
    accessible = JSONData.objects.annotate(shared_with_viewer=Exists(shares)).filter(
        Q(owner=request.user) | Q(access_type="all") | Q(shared_with_viewer=True),
    )
    obj = get_object_or_404(accessible, pk=int(value)) if value else None
    graph = None
    current = None
    if obj is not None:
        metadata = metadata_view(obj.data)
        graph = build_relationship_graph(
            metadata, _extract_plot_variables(metadata, units=metadata.get("units", {})),
        )
        current = _object_option(obj)

    choose = obj is None or request.GET.get("choose") == "1"
    query = request.GET.get("q", "").strip()
    context = {
        "data_object": obj, "current_object": current, "relationship_graph": graph,
        "choose_object": choose, "object_query": query, "object_options": [],
    }
    if choose:
        page, options = _object_choices(accessible, query, request.GET.get("page"))
        params = {"choose": "1", "q": query}
        if obj is not None:
            params["object"] = obj.pk
        context.update(object_options=options, option_page=page,
                       current_in_options=any(option["pk"] == obj.pk for option in options) if obj else False)
        if page.has_previous():
            context["previous_objects_url"] = reverse("graph") + "?" + urlencode(
                {**params, "page": page.previous_page_number()},
            )
        if page.has_next():
            context["next_objects_url"] = reverse("graph") + "?" + urlencode(
                {**params, "page": page.next_page_number()},
            )
    return render(request, "pages/graph.html", context)
