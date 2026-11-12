"""
Save private user supplied relationships without modifying uploaded metadata
"""

from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .collection_graph import CollectionSummaryPending, collection_summaries
from .collection_navigation import read_mutation_navigation
from .models import CollectionRelationship
from .research_collections import _owned_collection, _validate_access, _workspace_response, accessible_objects


MAX_COLLECTION_RELATIONSHIPS = 1000
UNAVAILABLE_RELATIONSHIP = "This relationship or one of its data objects is unavailable. Refresh the collection and try again."
STALE_RELATIONSHIP = "This relationship changed in another tab. Reload it before saving or deleting."


def _positive_id(value):
    """
    Accept one positive ASCII identifier within the database integer range

    Parameters
    ----------
    value : str
        Submitted identifier without surrounding whitespace.

    Returns
    -------
    int
        Validated numeric identifier.

    Raises
    ------
    forms.ValidationError
        The supplied identifier is malformed or outside the supported range.
    """
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise forms.ValidationError("Choose a valid data object or relationship.")
    number = int(value)
    if not 0 < number <= 9223372036854775807:
        raise forms.ValidationError("Choose a valid data object or relationship.")
    return number


class RelationshipForm(forms.Form):
    """
    Validate explicit link fields before checking collection membership and access
    """

    source = forms.CharField(strip=False, widget=forms.Select(attrs={"class": "form-control form-control-sm"}))
    target = forms.CharField(strip=False, widget=forms.Select(attrs={"class": "form-control form-control-sm"}))
    label = forms.CharField(max_length=120, widget=forms.TextInput(attrs={
        "class": "form-control form-control-sm", "placeholder": "For example: compared with",
    }))
    relationship_id = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)
    revision = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)

    def __init__(self, data=None, *, choices=(), **kwargs):
        """
        Populate endpoint controls without relying on client choices for access

        Parameters
        ----------
        data : QueryDict or dict or None, optional
            Submitted form fields.
        choices : iterable of tuple, optional
            Accessible member IDs and their visible descriptions.
        **kwargs : object
            Standard Django form construction options.
        """
        super().__init__(data, **kwargs)
        options = [("", "Choose a data object"), *choices]
        self.fields["source"].widget.choices = options
        self.fields["target"].widget.choices = options

    def clean(self):
        """
        Reject repeated fields, incomplete edit versions and self connections

        Returns
        -------
        dict
            Validated strings and integer endpoint identifiers.
        """
        cleaned = super().clean()
        for name in self.fields:
            if hasattr(self.data, "getlist") and len(self.data.getlist(name)) > 1:
                self.add_error(name, "Submit this field once.")
                continue
            if name in {"source", "target", "relationship_id", "revision"} and cleaned.get(name):
                try:
                    cleaned[name] = _positive_id(cleaned[name])
                except forms.ValidationError as exc:
                    self.add_error(name, exc)
        if bool(cleaned.get("relationship_id")) != bool(cleaned.get("revision")):
            self.add_error(None, "Reload the relationship before editing it.")
        if cleaned.get("source") and cleaned.get("source") == cleaned.get("target"):
            self.add_error("target", "Choose a different data object for the target.")
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in cleaned.get("label", "")):
            self.add_error("label", "Use a single line of text for the relationship name.")
        return cleaned


def accessible_relationships(user, collection):
    """
    Limit links to the owner's currently accessible collection members at both ends

    Parameters
    ----------
    user : User
        Authenticated viewer.
    collection : ResearchCollection
        Collection whose saved links are being queried.

    Returns
    -------
    QuerySet
        User supplied links that reveal no inaccessible endpoint or foreign collection.
    """
    members = accessible_objects(user).filter(research_collections=collection).values("pk")
    return CollectionRelationship.objects.filter(
        collection=collection, collection__owner=user, source_id__in=members, target_id__in=members,
    )


def _wants_json(request):
    """
    Recognize an explicit JSON response request without changing native form behavior

    Parameters
    ----------
    request : HttpRequest
        Incoming form request.

    Returns
    -------
    bool
        Whether Accept explicitly includes application/json.
    """
    return any(value.split(";", 1)[0].strip() == "application/json"
               for value in request.headers.get("Accept", "").split(","))


def _failure(request, collection, form, error, status=400, *, navigation_params=None):
    """
    Preserve submitted values while reporting a rejected mutation

    Parameters
    ----------
    request : HttpRequest
        Native or JSON requesting form submission.
    collection : ResearchCollection
        Collection restricted to the current owner.
    form : RelationshipForm
        Bound form retaining the user's input.
    error : str
        Actionable failure description without inaccessible metadata.
    status : int, optional
        Validation or conflict response status.
    navigation_params : dict or None, optional
        Validated workspace state to retain beside the bound form.

    Returns
    -------
    HttpResponse
        JSON feedback or the collection workspace with its bound form.
    """
    if _wants_json(request):
        return JsonResponse({"ok": False, "error": error, "errors": dict(form.errors)}, status=status)
    if navigation_params is not None:
        navigation_params = {**navigation_params, "links": "members", "panel": "explore"}
        navigation_params.pop("group", None)
        navigation_params.pop("edge", None)
    return _workspace_response(request, collection=collection, relationship_form=form, error=error, status=status,
                               navigation_params=navigation_params)


def _validate_members(user, collection, ids):
    """
    Lock and validate every old and new endpoint as one complete collection change

    Parameters
    ----------
    user : User
        Current collection owner.
    collection : ResearchCollection
        Collection already locked for this transaction.
    ids : set of int
        Every endpoint involved in the mutation.

    Raises
    ------
    ValueError
        Any endpoint is no longer accessible or no longer a collection member.
    """
    try:
        _validate_access(user, sorted(ids), lock=True)
    except ValueError:
        raise ValueError(UNAVAILABLE_RELATIONSHIP) from None
    if collection.members.filter(pk__in=ids).count() != len(ids):
        raise ValueError(UNAVAILABLE_RELATIONSHIP)


def _saved_fields(relationship):
    """
    Serialize the minimal confirmed relationship state for the graph editor

    Parameters
    ----------
    relationship : CollectionRelationship
        Saved and permission checked relationship.

    Returns
    -------
    dict
        Stable identity, endpoints, label and concurrency revision.
    """
    return {
        "id": relationship.pk, "source_id": relationship.source_id, "target_id": relationship.target_id,
        "label": relationship.label, "revision": relationship.revision,
    }


@login_required
@require_POST
def collection_relationship_save(request, pk):
    """
    Create or replace one explicitly supplied private collection relationship

    Parameters
    ----------
    request : HttpRequest
        POST with endpoints, label and an optional existing identity and revision.
    pk : int
        Collection owned by the signed in viewer.

    Returns
    -------
    HttpResponse
        Confirmed save or validation feedback without partial changes.
    """
    collection = _owned_collection(request, pk)
    form = RelationshipForm(request.POST)
    try:
        navigation = read_mutation_navigation(request, collection=collection)
    except ValueError as exc:
        return _failure(request, collection, form, str(exc), navigation_params={})
    return_params = None if navigation is None else {**navigation["params"], "panel": "explore"}
    if any(name in request.GET for name in form.fields):
        form.is_valid()
        form.add_error(None, "Submit relationship fields in the form only.")
    if not form.is_valid():
        return _failure(request, collection, form, "Check the relationship fields below.", navigation_params=return_params)
    fields = form.cleaned_data
    conflict = False
    try:
        with transaction.atomic():
            collection = _owned_collection(request, pk, lock=True)
            relationship = None
            endpoint_ids = {fields["source"], fields["target"]}
            if fields.get("relationship_id"):
                relationship = CollectionRelationship.objects.filter(
                    collection=collection, pk=fields["relationship_id"],
                ).first()
                if relationship is None:
                    raise ValueError(UNAVAILABLE_RELATIONSHIP)
                endpoint_ids.update((relationship.source_id, relationship.target_id))
            _validate_members(request.user, collection, endpoint_ids)
            if relationship is not None and relationship.revision != fields["revision"]:
                conflict = True
                raise ValueError(STALE_RELATIONSHIP)
            duplicate = collection.relationships.filter(
                source_id=fields["source"], target_id=fields["target"], label=fields["label"],
            )
            if relationship is not None:
                duplicate = duplicate.exclude(pk=relationship.pk)
            if duplicate.exists():
                form.add_error("label", "This relationship already exists between these objects.")
                raise ValueError("This relationship already exists. Edit its saved connection instead.")
            if relationship is None:
                if collection.relationships.count() >= MAX_COLLECTION_RELATIONSHIPS:
                    raise ValueError("This collection has reached its relationship limit. Remove a relationship or clear unavailable members first.")
                relationship = CollectionRelationship(collection=collection)
            else:
                relationship.revision += 1
            relationship.source_id = fields["source"]
            relationship.target_id = fields["target"]
            relationship.label = fields["label"]
            relationship.save()
            collection.save(update_fields=["updated_at"])
    except ValueError as exc:
        return _failure(request, collection, form, str(exc), status=409 if conflict else 400,
                        navigation_params=return_params)
    url = reverse("collection_detail", args=[collection.pk]) + f"?links=members&edge={relationship.pk}"
    if return_params is not None:
        return_params.update(links="members", edge=str(relationship.pk))
        return_params.pop("group", None)
        url = reverse("collection_detail", args=[collection.pk]) + "?" + urlencode(return_params)
    if _wants_json(request):
        return JsonResponse({"ok": True, "redirect_url": url, "relationship": _saved_fields(relationship)})
    messages.success(request, "Relationship saved in this collection. Original data objects are unchanged.")
    return redirect(url)


@login_required
@require_POST
def collection_relationship_delete(request, pk, relationship_pk):
    """
    Delete one visible manual connection only when its revision is still current

    Parameters
    ----------
    request : HttpRequest
        Explicit POST carrying the displayed relationship revision.
    pk : int
        Collection owned by the viewer.
    relationship_pk : int
        Saved relationship within that collection.

    Returns
    -------
    HttpResponse
        Deletion acknowledgement or feedback for an unchanged relationship.
    """
    collection = _owned_collection(request, pk)
    form = RelationshipForm(request.POST)
    try:
        navigation = read_mutation_navigation(request, collection=collection)
    except ValueError as exc:
        return _failure(request, collection, form, str(exc), navigation_params={})
    return_params = None if navigation is None else {**navigation["params"], "panel": "explore"}
    revisions = request.POST.getlist("revision")
    try:
        if len(revisions) != 1 or "revision" in request.GET:
            raise forms.ValidationError("Submit the relationship revision once.")
        revision = _positive_id(revisions[0])
    except forms.ValidationError as exc:
        return _failure(request, collection, form, str(exc.messages[0]), navigation_params=return_params)
    conflict = False
    try:
        with transaction.atomic():
            collection = _owned_collection(request, pk, lock=True)
            relationship = CollectionRelationship.objects.filter(collection=collection, pk=relationship_pk).first()
            if relationship is None:
                raise ValueError(UNAVAILABLE_RELATIONSHIP)
            _validate_members(request.user, collection, {relationship.source_id, relationship.target_id})
            form = RelationshipForm({
                "source": relationship.source_id, "target": relationship.target_id, "label": relationship.label,
                "relationship_id": relationship.pk, "revision": revision,
            })
            form.is_valid()
            if relationship.revision != revision:
                conflict = True
                raise ValueError(STALE_RELATIONSHIP)
            relationship.delete()
            collection.save(update_fields=["updated_at"])
    except ValueError as exc:
        return _failure(request, collection, form, str(exc), status=409 if conflict else 400,
                        navigation_params=return_params)
    url = reverse("collection_detail", args=[collection.pk]) + "?links=members#manual-relationships"
    if return_params is not None:
        return_params.update(links="members")
        return_params.pop("group", None)
        return_params.pop("edge", None)
        url = reverse("collection_detail", args=[collection.pk]) + "?" + urlencode(return_params) + "#manual-relationships"
    if _wants_json(request):
        return JsonResponse({"ok": True, "redirect_url": url})
    messages.success(request, "Relationship deleted. Original data objects are unchanged.")
    return redirect(url)


@login_required
@require_GET
def collection_relationship_export(request, pk):
    """
    Export accessible user supplied links separately from original data JSON

    Parameters
    ----------
    request : HttpRequest
        Authenticated export request.
    pk : int
        Collection owned by the viewer.

    Returns
    -------
    HttpResponse
        A versioned relationship document or a bounded preparation response.
    """
    collection = _owned_collection(request, pk)
    relationships = list(accessible_relationships(request.user, collection))
    endpoint_ids = set()
    for relationship in relationships:
        endpoint_ids.update((relationship.source_id, relationship.target_id))
    members = accessible_objects(request.user).filter(research_collections=collection, pk__in=endpoint_ids)
    try:
        summaries = {row["pk"]: row for row in collection_summaries(members)}
    except CollectionSummaryPending as exc:
        return JsonResponse({
            "ok": False, "error": "Collection metadata is being prepared. Open the collection and retry this export.",
            "ready_count": exc.ready_count, "total_count": exc.total_count,
        }, status=503 if exc.requires_admin else 202)
    rows = []
    for relationship in relationships:
        if relationship.source_id not in summaries or relationship.target_id not in summaries:
            continue
        endpoints = {}
        for name, object_id in (("source", relationship.source_id), ("target", relationship.target_id)):
            summary = summaries[object_id]
            endpoints[name] = {"id": object_id, "identifier": summary["identifier"], "title": summary["title"]}
        rows.append({
            "id": relationship.pk, **endpoints, "label": relationship.label,
            "origin": "user", "revision": relationship.revision,
        })
    response = JsonResponse({
        "format": "research-collection-relationships", "version": 1,
        "collection": {"id": collection.pk, "title": collection.title}, "relationships": rows,
    }, json_dumps_params={"ensure_ascii": False})
    response["Content-Disposition"] = f'attachment; filename="collection-{collection.pk}-relationships.json"'
    response["Cache-Control"] = "private, no-store"
    return response
