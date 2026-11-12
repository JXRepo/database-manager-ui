"""
Organize accessible records into private research collections
"""

import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import JSONData, ResearchCollection
from .collection_graph import CollectionSummaryPending
from .collection_navigation import CONTEXT_ERROR, navigation_fields, read_navigation, workspace_navigation
from .temporary_selections import append_selection, create_selection, selection_ids


MAX_SELECTION_OBJECTS = 500
MAX_COLLECTION_OBJECTS = 1000
MAX_TEMPORARY_SELECTIONS = 8
SELECTION_SESSION_KEY = "graph_selections"
UNAVAILABLE_SELECTION = "Some selected objects are unavailable. Refresh the list and select them again."


class CollectionForm(forms.Form):
    """
    Validate the editable description of a private collection
    """

    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={
        "class": "form-control form-control-sm", "placeholder": "Name this research collection",
    }))
    description = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={
        "class": "form-control form-control-sm", "rows": 3,
        "placeholder": "What brings these data objects together?",
    }))


def accessible_objects(user):
    """
    Restrict records to the viewer's owned, public and explicitly shared data

    Parameters
    ----------
    user : User
        Authenticated viewer.

    Returns
    -------
    QuerySet
        Accessible records without duplicates from sharing joins.
    """
    shares = JSONData.shared_users.through.objects.filter(
        jsondata_id=OuterRef("pk"), user_id=user.pk,
    )
    return JSONData.objects.annotate(shared_with_viewer=Exists(shares)).filter(
        Q(owner=user) | Q(access_type="all") | Q(shared_with_viewer=True),
    )


def _parse_ids(values):
    """
    Validate one bounded selection without silently discarding malformed entries

    Parameters
    ----------
    values : list of str
        Submitted record IDs.

    Returns
    -------
    list of int
        Distinct IDs in their supplied order.

    Raises
    ------
    ValueError
        Selection is empty, too large or contains an invalid ID.
    """
    if not values:
        raise ValueError("Select at least one data object.")
    if len(values) > MAX_SELECTION_OBJECTS:
        raise ValueError(f"Select up to {MAX_SELECTION_OBJECTS} data objects at a time.")
    ids = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 19:
            raise ValueError(UNAVAILABLE_SELECTION)
        number = int(value)
        if not 0 < number <= 9223372036854775807:
            raise ValueError(UNAVAILABLE_SELECTION)
        if number not in seen:
            ids.append(number)
            seen.add(number)
    return ids


def _validate_access(user, ids, *, lock=False):
    """
    Reject the entire selection when any requested record is unavailable

    Parameters
    ----------
    user : User
        Authenticated viewer.
    ids : list of int
        Previously validated record IDs.
    lock : bool, optional
        Lock records during a collection mutation.

    Returns
    -------
    QuerySet
        Records restricted to the complete validated selection.

    Raises
    ------
    ValueError
        At least one record is missing or inaccessible.
    """
    objects = accessible_objects(user).filter(pk__in=ids).order_by("pk")
    checked = objects.select_for_update() if lock else objects
    if len(list(checked.values_list("pk", flat=True))) != len(ids):
        raise ValueError(UNAVAILABLE_SELECTION)
    if lock and objects.count() != len(ids):
        # a share may have been revoked while the locking statement waited
        raise ValueError(UNAVAILABLE_SELECTION)
    return objects


def _selection_ids(request, token):
    """
    Read a temporary selection owned by the current authenticated session

    Parameters
    ----------
    request : HttpRequest
        Request with the session holding the selection.
    token : str
        Opaque selection token from a local URL.

    Returns
    -------
    list of int
        Stored record IDs, whose current access is checked separately.
    """
    return selection_ids(request, token)


def _owned_collection(request, pk, *, lock=False):
    """
    Resolve a collection without exposing another user's collection

    Parameters
    ----------
    request : HttpRequest
        Authenticated request.
    pk : int
        Requested collection ID.
    lock : bool, optional
        Serialize membership changes inside a transaction.

    Returns
    -------
    ResearchCollection
        Collection owned by the viewer.
    """
    collections = ResearchCollection.objects.filter(owner=request.user)
    if lock:
        collections = collections.select_for_update()
    return get_object_or_404(collections, pk=pk)


def _index_response(request, *, error="", status=200):
    """
    Render the viewer's collections with accessible member counts only

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with optional collection search and page.
    error : str, optional
        Selection error to show beside the workspace entry.
    status : int, optional
        HTTP response status.

    Returns
    -------
    HttpResponse
        A bounded collection list.
    """
    query = request.GET.get("q", "").strip()
    collections = ResearchCollection.objects.filter(owner=request.user).annotate(
        visible_count=Count("members", filter=Q(members__in=accessible_objects(request.user)), distinct=True),
    ).order_by("-updated_at", "-pk")
    if query:
        collections = collections.filter(title__icontains=query)
    page = Paginator(collections, 25).get_page(request.GET.get("page"))
    return render(request, "pages/collections.html", {
        "collections": page.object_list, "collection_page": page,
        "collection_query": query, "selection_error": error,
    }, status=status)


def _graph_context(objects, *, title, base_url, params, manual_relationships=()):
    """
    Build graph summaries after the view has enforced record access

    Parameters
    ----------
    objects : QuerySet
        Accessible records in the current collection or temporary selection.
    title : str
        Workspace title.
    base_url : str
        Local workspace URL.
    params : QueryDict
        Requested grouping and navigation options.
    manual_relationships : sequence of dict, optional
        Separately stored collection relationships with accessible endpoints.

    Returns
    -------
    dict
        Graph and member list context.
    """
    from .collection_graph import build_collection_context

    return build_collection_context(objects, title=title, base_url=base_url, params=params,
                                    manual_relationships=manual_relationships)


def _workspace_response(request, *, collection=None, token="", form=None, error="", status=200,
                        navigation_params=None, relationship_form=None):
    """
    Render a selection or collection using only currently accessible members

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    collection : ResearchCollection or None, optional
        Saved collection already restricted to its owner.
    token : str, optional
        Temporary selection token when no collection is supplied.
    form : CollectionForm or None, optional
        Bound form to preserve validation feedback.
    error : str, optional
        Failed action description.
    status : int, optional
        HTTP response status.
    navigation_params : dict or None, optional
        Verified original workspace scope when a continuation action fails.
    relationship_form : RelationshipForm or None, optional
        Submitted manual relationship values and errors to preserve.

    Returns
    -------
    HttpResponse
        Workspace with forms, graph summaries and accessible member rows.
    """
    if collection is not None:
        objects = accessible_objects(request.user).filter(research_collections=collection)
        title = collection.title
        url = reverse("collection_detail", args=[collection.pk])
        export_url = reverse("collection_export", args=[collection.pk])
        initial = {"title": collection.title, "description": collection.description}
    else:
        objects = accessible_objects(request.user).filter(pk__in=_selection_ids(request, token))
        title = "Selected data objects"
        url = reverse("selection_detail", args=[token])
        export_url = reverse("selection_export", args=[token])
        initial = {}
    context = {
        "collection": collection, "selection_token": token,
        "collection_form": form if form is not None else CollectionForm(initial=initial),
        "available_collections": ResearchCollection.objects.filter(owner=request.user).only("pk", "title").order_by("title", "pk"),
        "workspace_title": title, "workspace_url": url, "export_url": export_url,
        "selection_error": error, "action_error": error,
    }
    try:
        params = request.GET if navigation_params is None else navigation_params
        manual_rows = []
        if collection is not None:
            from .collection_relationships import accessible_relationships

            manual_rows = list(accessible_relationships(request.user, collection).values(
                "id", "source_id", "target_id", "label", "revision",
            ))
        graph_options = {"manual_relationships": manual_rows} if manual_rows else {}
        context.update(_graph_context(objects, title=title, base_url=url, params=params, **graph_options))
        if "manual_member_summaries" in context:
            from .study_workspace import build_study_workspace_context

            context.update(build_study_workspace_context(
                objects, context, params, base_url=url, collection=collection, selection_token=token,
            ))
            if context["study_workspace"]["error"] and status < 400:
                status = 400
            preparation = context["study_comparison"].get("preparation")
            if preparation and status < 400:
                status = 503 if preparation["requires_admin"] else 202
        if collection is not None and "manual_member_summaries" in context:
            from .collection_relationship_context import relationship_editor_context

            context["manual_editor"] = relationship_editor_context(collection, context, params,
                                                                  form=relationship_form)
        if "relationship_graph" in context:
            context.update(workspace_navigation(request, context, collection=collection,
                                                selection_token=token))
    except CollectionSummaryPending as exc:
        context.update(
            summary_preparation={
                "ready_count": exc.ready_count, "total_count": exc.total_count,
                "requires_admin": exc.requires_admin,
            },
            object_total=exc.total_count, object_rows=[], relationship_graph=None,
            graph_error=False,
        )
        if status < 400:
            status = 503 if exc.requires_admin else 202
    except ValueError as exc:
        context.update(selection_error=str(exc), action_error=str(exc), graph_error=True,
                       object_rows=[], object_total=0)
        status = 400
    return render(request, "pages/collection_graph.html", context, status=status)


def _extend_selection(request, navigation, ids):
    """
    Add the whole submitted selection to its original workspace atomically

    Parameters
    ----------
    request : HttpRequest
        Authenticated continuation POST.
    navigation : dict
        Validated original collection or session selection.
    ids : list of int
        Bounded submitted IDs, whose access is checked during the change.

    Returns
    -------
    HttpResponse
        Redirect to the original group, page and presentation.

    Raises
    ------
    ValueError
        Any object is unavailable or the complete union exceeds capacity.
    """
    if navigation["kind"] == "collection":
        with transaction.atomic():
            collection = _owned_collection(request, navigation["collection"].pk, lock=True)
            _validate_access(request.user, ids, lock=True)
            existing = set(collection.members.values_list("pk", flat=True))
            if len(existing.union(ids)) > MAX_COLLECTION_OBJECTS:
                raise ValueError(
                    f"A research collection can contain up to {MAX_COLLECTION_OBJECTS} data objects. "
                    "Remove some members, or use Edit collection to clear unavailable members, then try again."
                )
            added = set(ids) - existing
            if added:
                collection.members.add(*added)
                collection.save(update_fields=["updated_at"])
            navigation["collection"] = collection
        message = ("Selected objects added to the collection." if added
                   else "The selected objects are already in this collection.")
    else:
        token = navigation["selection_token"]
        added = append_selection(request, token, ids)
        message = ("Selected objects added to this selection." if added
                   else "The selected objects are already in this selection.")
    messages.success(request, message)
    return redirect(navigation_fields(navigation)["graph_return_url"])


def _collection_form(data):
    """
    Reject repeated form fields instead of choosing one submitted value

    Parameters
    ----------
    data : QueryDict
        Submitted title and description.

    Returns
    -------
    CollectionForm
        Validated form with duplicate field errors where applicable.
    """
    form = CollectionForm(data)
    form.is_valid()
    for field in ("title", "description"):
        if len(data.getlist(field)) > 1:
            form.add_error(field, "Provide this field once.")
    return form


@login_required
@require_GET
def collection_index(request):
    """
    Show the signed-in user's private research collections

    Parameters
    ----------
    request : HttpRequest
        Authenticated collection list request.

    Returns
    -------
    HttpResponse
        Paginated collection list.
    """
    return _index_response(request)


@login_required
@require_POST
def selection_create(request):
    """
    Open a validated selection or extend the original collection workspace

    Parameters
    ----------
    request : HttpRequest
        POST containing selected_objects and optional signed graph_context.

    Returns
    -------
    HttpResponse
        Redirect to a temporary workspace or an actionable selection error.
    """
    navigation = None
    try:
        if "graph_context" in request.GET:
            raise ValueError(CONTEXT_ERROR)
        navigation = read_navigation(request, data=request.POST)
        ids = _parse_ids(request.POST.getlist("selected_objects"))
        if navigation is not None:
            return _extend_selection(request, navigation, ids)
        token = create_selection(request, ids)
    except ValueError as exc:
        if navigation is not None:
            return _workspace_response(
                request, collection=navigation.get("collection"),
                token=navigation.get("selection_token", ""), navigation_params=navigation["params"],
                error=str(exc), status=400,
            )
        return _index_response(request, error=str(exc), status=400)
    return redirect("selection_detail", token=token)


@login_required
@require_GET
def selection_detail(request, token):
    """
    Explore a temporary selection with permissions checked on every visit

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    token : str
        Selection token belonging to this session.

    Returns
    -------
    HttpResponse
        Current accessible selection.
    """
    return _workspace_response(request, token=token)


@login_required
@require_GET
def collection_detail(request, pk):
    """
    Explore accessible members of a saved private collection

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    pk : int
        Requested collection ID.

    Returns
    -------
    HttpResponse
        Current accessible collection members.
    """
    return _workspace_response(request, collection=_owned_collection(request, pk))


@login_required
@require_POST
def collection_save(request, token):
    """
    Save a complete accessible selection as a named private collection

    Parameters
    ----------
    request : HttpRequest
        POST with title and optional description.
    token : str
        Temporary selection token belonging to the session.

    Returns
    -------
    HttpResponse
        Saved collection or the existing workspace with validation errors.
    """
    from urllib.parse import urlencode

    from .collection_navigation import read_mutation_navigation

    ids = _selection_ids(request, token)
    form = _collection_form(request.POST)
    try:
        navigation = read_mutation_navigation(request, selection_token=token)
    except ValueError as exc:
        return _workspace_response(request, token=token, form=form, error=str(exc), status=400,
                                   navigation_params={})
    return_params = navigation["params"] if navigation is not None else None
    if not form.is_valid():
        return _workspace_response(request, token=token, form=form, status=400, navigation_params=return_params)
    try:
        with transaction.atomic():
            _validate_access(request.user, ids, lock=True)
            collection = ResearchCollection.objects.create(owner=request.user, **form.cleaned_data)
            collection.members.add(*ids)
    except ValueError as exc:
        return _workspace_response(request, token=token, form=form, error=str(exc), status=400,
                                   navigation_params=return_params)
    messages.success(request, "Research collection saved. Only you can access this collection.")
    if return_params:
        return redirect(reverse("collection_detail", args=[collection.pk]) + "?" + urlencode(return_params))
    return redirect("collection_detail", pk=collection.pk)


@login_required
@require_POST
def collection_update(request, pk):
    """
    Update a collection's description without changing its records

    Parameters
    ----------
    request : HttpRequest
        POST with the revised title and description.
    pk : int
        Collection owned by the current user.

    Returns
    -------
    HttpResponse
        Updated collection or editable validation errors.
    """
    collection = _owned_collection(request, pk)
    form = _collection_form(request.POST)
    if not form.is_valid():
        return _workspace_response(request, collection=collection, form=form, status=400)
    with transaction.atomic():
        collection = _owned_collection(request, pk, lock=True)
        collection.title = form.cleaned_data["title"]
        collection.description = form.cleaned_data["description"]
        collection.save(update_fields=["title", "description", "updated_at"])
    messages.success(request, "Collection details updated.")
    return redirect("collection_detail", pk=collection.pk)


@login_required
@require_POST
def collection_add(request, token):
    """
    Add all selected records to an owned collection as one atomic change

    Parameters
    ----------
    request : HttpRequest
        POST with one target collection_id.
    token : str
        Temporary selection to add.

    Returns
    -------
    HttpResponse
        Updated collection or the unchanged selection with an error.
    """
    ids = _selection_ids(request, token)
    try:
        targets = request.POST.getlist("collection_id")
        if len(targets) != 1:
            raise ValueError("Choose one research collection.")
        target = _parse_ids(targets)[0]
        with transaction.atomic():
            collection = _owned_collection(request, target, lock=True)
            _validate_access(request.user, ids, lock=True)
            existing = set(collection.members.values_list("pk", flat=True))
            if len(existing.union(ids)) > MAX_COLLECTION_OBJECTS:
                raise ValueError(
                    f"A research collection can contain up to {MAX_COLLECTION_OBJECTS} data objects. "
                    "Remove some members, or use Edit collection to clear unavailable members, then try again."
                )
            collection.members.add(*ids)
            collection.save(update_fields=["updated_at"])
    except ValueError as exc:
        return _workspace_response(request, token=token, error=str(exc), status=400)
    messages.success(request, "Selected objects added to the collection.")
    return redirect("collection_detail", pk=collection.pk)


@login_required
@require_POST
def collection_remove(request, pk):
    """
    Remove selected members from a collection while retaining their data

    Parameters
    ----------
    request : HttpRequest
        POST containing selected_objects from the displayed member list.
    pk : int
        Collection owned by the current user.

    Returns
    -------
    HttpResponse
        Updated collection or a selection error without partial removal.
    """
    collection = _owned_collection(request, pk)
    try:
        ids = _parse_ids(request.POST.getlist("selected_objects"))
        with transaction.atomic():
            collection = _owned_collection(request, pk, lock=True)
            _validate_access(request.user, ids, lock=True)
            if collection.members.filter(pk__in=ids).count() != len(ids):
                raise ValueError(UNAVAILABLE_SELECTION)
            collection.relationships.filter(Q(source_id__in=ids) | Q(target_id__in=ids)).delete()
            collection.members.remove(*ids)
            collection.save(update_fields=["updated_at"])
    except ValueError as exc:
        return _workspace_response(request, collection=collection, error=str(exc), status=400)
    messages.success(request, "Objects removed from the collection. The data objects are unchanged.")
    return redirect("collection_detail", pk=collection.pk)


@login_required
@require_POST
def collection_cleanup(request, pk):
    """
    Clear unavailable member references without revealing or modifying their data

    Parameters
    ----------
    request : HttpRequest
        Explicit POST from the collection's owner.
    pk : int
        Collection whose unavailable references should be removed.

    Returns
    -------
    HttpResponse
        Redirect with the same acknowledgement whether any references changed.
    """
    with transaction.atomic():
        collection = _owned_collection(request, pk, lock=True)
        memberships = collection.members.through.objects.select_for_update().filter(
            researchcollection_id=collection.pk,
        ).order_by("pk")
        member_ids = list(memberships.values_list("jsondata_id", flat=True))
        visible_ids = set(accessible_objects(request.user).filter(pk__in=member_ids).values_list("pk", flat=True))
        unavailable_ids = []
        for member_id in member_ids:
            if member_id not in visible_ids:
                unavailable_ids.append(member_id)
        collection.relationships.filter(Q(source_id__in=unavailable_ids) | Q(target_id__in=unavailable_ids)).delete()
        collection.members.remove(*unavailable_ids)
        collection.save(update_fields=["updated_at"])
    messages.success(request, "Unavailable members cleared. Data objects are unchanged.")
    return redirect("collection_detail", pk=collection.pk)


@login_required
@require_POST
def collection_delete(request, pk):
    """
    Delete an owned collection without deleting its data objects

    Parameters
    ----------
    request : HttpRequest
        Authenticated deletion request.
    pk : int
        Collection owned by the current user.

    Returns
    -------
    HttpResponse
        Redirect to the remaining collections.
    """
    with transaction.atomic():
        _owned_collection(request, pk, lock=True).delete()
    messages.success(request, "Collection deleted. Its data objects are unchanged.")
    return redirect("collection_index")


def _json_rows(objects):
    """
    Stream original records as one JSON array without retaining the whole set

    Parameters
    ----------
    objects : QuerySet
        Records whose current access has already been checked.

    Yields
    ------
    str
        JSON array fragments containing unchanged stored records.
    """
    yield "["
    first = True
    iterator = objects.only("data").order_by("pk").iterator(chunk_size=1)
    try:
        for obj in iterator:
            if not first:
                yield ","
            yield json.dumps(obj.data, ensure_ascii=False)
            first = False
    finally:
        iterator.close()
    yield "]"


def _export_response(objects, filename):
    """
    Download original JSON records with a fixed, server generated filename

    Parameters
    ----------
    objects : QuerySet
        Accessible records to export.
    filename : str
        Safe filename chosen by the view.

    Returns
    -------
    StreamingHttpResponse
        Downloadable JSON array.
    """
    response = StreamingHttpResponse(_json_rows(objects), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def collection_export(request, pk):
    """
    Export currently accessible members of the viewer's collection

    Parameters
    ----------
    request : HttpRequest
        Authenticated download request.
    pk : int
        Collection owned by the viewer.

    Returns
    -------
    StreamingHttpResponse
        Accessible original JSON records, excluding revoked members.
    """
    collection = _owned_collection(request, pk)
    objects = accessible_objects(request.user).filter(research_collections=collection)
    return _export_response(objects, f"research-collection-{collection.pk}.json")


@login_required
@require_GET
def selection_export(request, token):
    """
    Export a temporary selection only while every selected record is accessible

    Parameters
    ----------
    request : HttpRequest
        Authenticated download request.
    token : str
        Temporary selection belonging to the session.

    Returns
    -------
    HttpResponse
        Complete original JSON array or an explicit selection error.
    """
    ids = _selection_ids(request, token)
    try:
        objects = _validate_access(request.user, ids)
    except ValueError as exc:
        return _workspace_response(request, token=token, error=str(exc), status=400)
    return _export_response(objects, "selected-research-data.json")
