"""
Save private study choices with explicit revisions and current source checks.
"""

import json
import re
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connections, transaction
from django.db.models import BigIntegerField, BinaryField, F, Func, TextField
from django.db.models.functions import Cast, MD5
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import SavedStudyAnalysis


MAX_ANALYSES = 100
MAX_STATE_BYTES = 16 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
ANALYSIS_PAGE_SIZE = 12
UNAVAILABLE_ANALYSIS = "This analysis or one of its source records is unavailable. Choose accessible records from this collection again."
SOURCE_LIMIT = "These records exceed the 16 MiB saved analysis limit. Choose fewer or smaller records, or open their individual source pages."
STALE_ANALYSIS = "This analysis changed in another tab. Your text has been kept. Open the current saved analysis before updating or deleting it."


def _positive_number(value, *, page=False):
    """
    Validate a bounded ASCII analysis identity or page.

    Parameters
    ----------
    value : str
        Submitted scalar text.
    page : bool, optional
        Use the smaller pagination range.

    Returns
    -------
    int
        Valid positive integer.

    Raises
    ------
    ValueError
        The value is malformed or outside the supported range.
    """
    maximum = 2147483647 if page else 9223372036854775807
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > maximum:
        raise ValueError("Choose a valid saved analysis or page.")
    return int(value)


def analysis_parameters(params):
    """
    Validate active analysis and list pagination before signing navigation.

    Parameters
    ----------
    params : QueryDict or dict
        Native workspace controls.

    Returns
    -------
    dict
        Canonical nondefault scalar values.
    """
    result = {}
    for key in ("analysis", "analyses_page"):
        values = params.getlist(key) if hasattr(params, "getlist") else ([params[key]] if key in params else [])
        if len(values) > 1:
            raise ValueError("Choose each saved analysis option once.")
        if values:
            value = _positive_number(values[0], page=key == "analyses_page")
            if key == "analysis" or value != 1:
                result[key] = str(value)
    return result


def _canonical_state(value, *, require_selection=True):
    """
    Restrict saved choices to the existing validated workspace controls.

    Parameters
    ----------
    value : dict
        Parsed flat workspace state.
    require_selection : bool, optional
        Require the two to four records needed for a saved analysis.

    Returns
    -------
    dict
        Canonical known state without active analysis or list identity.

    Raises
    ------
    ValueError
        State, controls or selected record IDs are invalid.
    """
    from .collection_navigation import _return_parameters
    from .study_comparison import parse_comparison_ids
    from .study_workspace import STUDY_PARAMETERS, study_parameters

    if not isinstance(value, dict) or set(value).intersection({"analysis", "analyses_page"}):
        raise ValueError("Use the current workspace controls to save this analysis.")
    checked = _return_parameters(value)
    result = {key: item for key, item in checked.items() if key not in STUDY_PARAMETERS}
    result.update(study_parameters(checked))
    for key in ("page", "groups_page", "relationships_page"):
        if result.get(key) == "1":
            result.pop(key)
    if result.get("view") == "compact":
        result.pop("view")
    if require_selection and not 2 <= len(parse_comparison_ids(result)) <= 4:
        raise ValueError("Choose two to four accessible records before saving an analysis.")
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("These workspace choices are too long to save. Shorten the search text and try again.")
    return result


def _unique_object(pairs):
    """
    Reject duplicate JSON keys rather than silently choosing a value.

    Parameters
    ----------
    pairs : list of tuple
        Object entries supplied by the JSON decoder.

    Returns
    -------
    dict
        Unambiguous parsed object.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Submit each workspace option once.")
        result[key] = value
    return result


class AnalysisForm(forms.Form):
    """
    Preserve user notes while validating explicit analysis state and revisions.
    """

    title = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"maxlength": 120, "placeholder": "Name this analysis"}))
    notes = forms.CharField(required=False, max_length=5000, strip=False,
                            widget=forms.Textarea(attrs={"rows": 3, "maxlength": 5000, "placeholder": "Your observations and next steps"}))
    workspace_state = forms.CharField(strip=False, widget=forms.HiddenInput)
    analysis_id = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)
    revision = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)
    intent = forms.ChoiceField(choices=(("create", "Save as new"), ("update", "Save changes")), widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        """
        Keep analysis labels distinct from collection and relationship editors.

        Parameters
        ----------
        *args : object
            Standard Django form construction arguments.
        **kwargs : object
            Standard Django form options, including optional initial values.
        """
        kwargs.setdefault("auto_id", "study-analysis-%s")
        super().__init__(*args, **kwargs)

    def clean(self):
        """
        Validate bounded text and state without discarding failed input.

        Returns
        -------
        dict
            Clean scalar fields and parsed canonical state.
        """
        cleaned = super().clean()
        for name in self.fields:
            if hasattr(self.data, "getlist") and len(self.data.getlist(name)) > 1:
                self.add_error(name, "Submit this field once.")
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 or char in "\u2028\u2029" for char in cleaned.get("title", "")):
            self.add_error("title", "Use a single line for the analysis name.")
        state_text = cleaned.get("workspace_state")
        if state_text is not None:
            try:
                if len(state_text.encode("utf-8")) > MAX_STATE_BYTES:
                    raise ValueError("These workspace choices are too long to save.")
                cleaned["state"] = _canonical_state(json.loads(state_text, object_pairs_hook=_unique_object))
            except (ValueError, TypeError, RecursionError, UnicodeError):
                self.add_error("workspace_state", "Use a valid comparison of two to four records and current workspace controls.")
        for name in ("analysis_id", "revision"):
            if cleaned.get(name):
                try:
                    cleaned[name] = _positive_number(cleaned[name])
                except ValueError as exc:
                    self.add_error(name, str(exc))
        if cleaned.get("intent") == "update" and not (cleaned.get("analysis_id") and cleaned.get("revision")):
            self.add_error(None, "Open the saved analysis before updating it.")
        return cleaned


def _source_digests(user, collection, state):
    """
    Check the entire selection and fingerprint bounded JSON within its transaction.

    Access is checked again after ordered object locks, so a concurrent share
    revocation cannot leave a saved baseline for a record the user no longer sees.

    Parameters
    ----------
    user : User
        Collection owner performing the inspection.
    collection : ResearchCollection
        Collection already locked in the current transaction.
    state : dict
        Canonical selected record controls.

    Returns
    -------
    dict
        Original record IDs mapped to database JSON digests, without raw data.

    Raises
    ------
    ValueError
        Any record is unavailable or the combined source bytes exceed the bound.
    """
    from .research_collections import accessible_objects
    from .study_comparison import parse_comparison_ids

    ids = parse_comparison_ids(state)
    if not 2 <= len(ids) <= 4:
        raise ValueError(UNAVAILABLE_ANALYSIS)
    selected = accessible_objects(user).filter(research_collections=collection, pk__in=ids).order_by("pk")
    if list(selected.select_for_update().values_list("pk", flat=True)) != sorted(ids):
        raise ValueError(UNAVAILABLE_ANALYSIS)
    if list(selected.values_list("pk", flat=True)) != sorted(ids):
        raise ValueError(UNAVAILABLE_ANALYSIS)
    postgres = connections[selected.db].vendor == "postgresql"
    byte_length = Func(Cast(F("data"), TextField() if postgres else BinaryField()),
                       function="OCTET_LENGTH" if postgres else "LENGTH", output_field=BigIntegerField())
    sizes = list(selected.annotate(raw_bytes=byte_length).values_list("raw_bytes", flat=True))
    if len(sizes) != len(ids):
        raise ValueError(UNAVAILABLE_ANALYSIS)
    if any(size is None or size <= 0 for size in sizes) or sum(sizes) > MAX_SOURCE_BYTES:
        raise ValueError(SOURCE_LIMIT)
    return {str(pk): digest for pk, digest in selected.annotate(source_digest=MD5(Cast("data", TextField())))
            .values_list("pk", "source_digest")}


def _json_response(request):
    """
    Recognize an explicit JSON enhancement without changing native submissions.

    Parameters
    ----------
    request : HttpRequest
        Incoming mutation request.

    Returns
    -------
    bool
        Whether the caller accepts JSON feedback.
    """
    return any(value.split(";", 1)[0].strip() == "application/json"
               for value in request.headers.get("Accept", "").split(","))


def _failure(request, collection, form, error, *, state=None, status=400, analysis_id=None):
    """
    Preserve a failed form through either native or enhanced feedback.

    Parameters
    ----------
    request : HttpRequest
        Original request.
    collection : ResearchCollection
        Owned collection.
    form : AnalysisForm
        Submitted fields and validation errors.
    error : str
        Safe user-facing explanation.
    state : dict or None, optional
        Validated state to retain in the workspace.
    status : int, optional
        HTTP validation or revision conflict status.
    analysis_id : int or None, optional
        Owned active analysis identity.

    Returns
    -------
    HttpResponse
        Failure retaining entered text without performing a mutation.
    """
    form.add_error(None, error)
    if _json_response(request):
        return JsonResponse({"ok": False, "error": error, "errors": dict(form.errors)}, status=status)
    from .research_collections import _workspace_response

    params = dict(state or {"links": "members", "panel": "compare"})
    if analysis_id:
        params["analysis"] = str(analysis_id)
    return _workspace_response(request, collection=collection, analysis_form=form,
                               error=error, status=status, navigation_params=params)


def _signed_scope(request, collection):
    """
    Require a current signed mutation context for exactly this collection.

    Parameters
    ----------
    request : HttpRequest
        Mutation carrying its signed navigation token.
    collection : ResearchCollection
        Already owned collection.

    Returns
    -------
    dict
        Validated navigation context.
    """
    from .collection_navigation import CONTEXT_ERROR, read_mutation_navigation

    navigation = read_mutation_navigation(request, collection=collection)
    if navigation is None:
        raise ValueError(CONTEXT_ERROR)
    return navigation


@login_required
@require_POST
def collection_analysis_save(request, pk):
    """
    Save a new private analysis or explicitly replace its matching revision.

    Parameters
    ----------
    request : HttpRequest
        Native or enhanced form with a complete selected state.
    pk : int
        Owned collection identity.

    Returns
    -------
    HttpResponse
        Confirmed redirect or retained validation/conflict feedback.
    """
    from .research_collections import _owned_collection

    collection = _owned_collection(request, pk)
    form = AnalysisForm(request.POST)
    try:
        _signed_scope(request, collection)
    except ValueError as exc:
        return _failure(request, collection, form, str(exc))
    if not form.is_valid():
        state = form.cleaned_data.get("state")
        identity = form.cleaned_data.get("analysis_id") if form.cleaned_data.get("intent") == "update" else None
        if identity and not SavedStudyAnalysis.objects.filter(pk=identity, collection=collection).exists():
            identity = None
        return _failure(request, collection, form, "Check the analysis fields and save again.",
                        state=state, analysis_id=identity)
    values = form.cleaned_data
    state = values["state"]
    identity = values.get("analysis_id") if values["intent"] == "update" else None
    try:
        with transaction.atomic():
            collection = _owned_collection(request, pk, lock=True)
            analysis = None
            if identity:
                analysis = SavedStudyAnalysis.objects.filter(pk=identity, collection=collection).first()
                if analysis is None:
                    raise ValueError(UNAVAILABLE_ANALYSIS)
                if analysis.revision != values["revision"]:
                    return _failure(request, collection, form, STALE_ANALYSIS, state=state, status=409, analysis_id=identity)
            elif SavedStudyAnalysis.objects.filter(collection=collection).count() >= MAX_ANALYSES:
                raise ValueError(f"This collection already has {MAX_ANALYSES} saved analyses. Delete an unused analysis before saving another.")
            digests = _source_digests(request.user, collection, state)
            if analysis is None:
                analysis = SavedStudyAnalysis(collection=collection)
            else:
                analysis.revision += 1
            analysis.title = values["title"]
            analysis.notes = values["notes"]
            analysis.state = state
            analysis.source_digests = digests
            analysis.save()
    except ValueError as exc:
        return _failure(request, collection, form, str(exc), state=state, analysis_id=identity)
    target = reverse("collection_detail", args=[collection.pk]) + "?" + urlencode({**state, "analysis": str(analysis.pk)})
    if _json_response(request):
        return JsonResponse({"ok": True, "redirect_url": target, "id": analysis.pk, "revision": analysis.revision})
    messages.success(request, "Analysis saved.")
    return redirect(target)


@login_required
@require_GET
def collection_analysis_open(request, pk, analysis_pk):
    """
    Reopen a complete saved selection after rechecking its current source access.

    Parameters
    ----------
    request : HttpRequest
        Authenticated read request.
    pk : int
        Owned collection identity.
    analysis_pk : int
        Analysis belonging to that collection.

    Returns
    -------
    HttpResponse
        Complete saved controls or an unavailable workspace without hidden records.
    """
    from .research_collections import _owned_collection, _workspace_response

    collection = _owned_collection(request, pk)
    analysis = get_object_or_404(SavedStudyAnalysis, collection=collection, pk=analysis_pk)
    try:
        state = _canonical_state(analysis.state)
        with transaction.atomic():
            collection = _owned_collection(request, pk, lock=True)
            _source_digests(request.user, collection, state)
    except ValueError as exc:
        return _workspace_response(request, collection=collection, error=str(exc), status=400,
                                   navigation_params={"analysis": str(analysis.pk), "links": "members", "panel": "compare"})
    return redirect(reverse("collection_detail", args=[pk]) + "?" + urlencode({**state, "analysis": str(analysis.pk)}))


@login_required
@require_POST
def collection_analysis_delete(request, pk, analysis_pk):
    """
    Delete only the named analysis after a signed scope and revision check.

    Parameters
    ----------
    request : HttpRequest
        Explicit deletion request with the last displayed revision.
    pk : int
        Owned collection identity.
    analysis_pk : int
        Analysis to delete without changing its source data.

    Returns
    -------
    HttpResponse
        Confirmed deletion or a retained conflict message.
    """
    from .research_collections import _owned_collection

    collection = _owned_collection(request, pk)
    analysis = get_object_or_404(SavedStudyAnalysis, collection=collection, pk=analysis_pk)
    initial = {"title": analysis.title, "notes": analysis.notes, "analysis_id": str(analysis.pk),
               "revision": request.POST.get("revision", ""),
               "workspace_state": json.dumps({"links": "members", "panel": "compare"}), "intent": "update"}
    form = AnalysisForm(initial)
    try:
        navigation = _signed_scope(request, collection)
        if len(request.POST.getlist("revision")) != 1:
            raise ValueError("Submit the displayed analysis revision once.")
        revision = _positive_number(request.POST["revision"])
        with transaction.atomic():
            collection = _owned_collection(request, pk, lock=True)
            analysis = get_object_or_404(SavedStudyAnalysis, collection=collection, pk=analysis_pk)
            if analysis.revision != revision:
                return _failure(request, collection, form, STALE_ANALYSIS, status=409, analysis_id=analysis.pk)
            analysis.delete()
    except ValueError as exc:
        return _failure(request, collection, form, str(exc), analysis_id=analysis.pk)
    state = {key: value for key, value in navigation["params"].items() if key not in {"analysis", "analyses_page"}}
    target = reverse("collection_detail", args=[pk])
    if state:
        target += "?" + urlencode(state)
    if _json_response(request):
        return JsonResponse({"ok": True, "redirect_url": target})
    messages.success(request, "Analysis deleted. Its data objects are unchanged.")
    return redirect(target)


def _workspace_state(context):
    """
    Assemble current canonical controls independently of active saved choices.

    Parameters
    ----------
    context : dict
        Completed workspace context with current canonical study state.

    Returns
    -------
    dict
        Current state suitable for a native save form.
    """
    state = {key: value for key, value in context.get("study_return_params", {}).items()
             if key not in {"analysis", "analyses_page"}}
    state["links"] = context.get("links_mode", state.get("links", "members"))
    if context.get("graph_view_mode") == "detailed":
        state["view"] = "detailed"
    if context.get("selected_group"):
        state["group"] = context["selected_group"]["key"]
    if context.get("manual_selected"):
        state["edge"] = str(context["manual_selected"]["id"])
    for key, field in (("page", "object_page"), ("groups_page", "group_page")):
        page = context.get(field)
        if page is not None and page.number > 1:
            state[key] = str(page.number)
    if context.get("manual_editor") and context["manual_editor"]["page"].number > 1:
        state["relationships_page"] = str(context["manual_editor"]["page"].number)
    return _canonical_state(state, require_selection=False)


def build_analysis_context(request, context, params, *, collection=None, form=None):
    """
    Show private analysis choices, current notes and accessible source-change status.

    Parameters
    ----------
    request : HttpRequest
        Authenticated workspace request.
    context : dict
        Existing canonical graph and study context.
    params : QueryDict or dict
        Current active analysis and list controls.
    collection : ResearchCollection or None, optional
        Owned saved collection; temporary selections cannot save analyses yet.
    form : AnalysisForm or None, optional
        Bound failed submission whose exact text remains visible.

    Returns
    -------
    dict
        Compact list, active metadata, saved-state comparison and native form.
    """
    from .research_collections import _owned_collection, accessible_objects
    from .study_comparison import parse_comparison_ids

    result = {"enabled": collection is not None, "active": None, "rows": [], "page": None,
              "previous_url": "", "next_url": "", "save_url": "", "state_json": "{}",
              "active_state_json": "{}", "can_save": False, "form": form, "error": ""}
    if collection is None:
        return result
    if collection.owner_id != request.user.pk:
        raise Http404
    base_url = reverse("collection_detail", args=[collection.pk])
    result["save_url"] = reverse("collection_analysis_save", args=[collection.pk])
    try:
        controls = analysis_parameters(params)
        state = _workspace_state(context)
    except ValueError as exc:
        result["error"] = str(exc)
        controls, state = {}, {"links": "members"}
    result["state_json"] = json.dumps(state, ensure_ascii=False)
    ids = parse_comparison_ids(state)
    if 2 <= len(ids) <= 4:
        result["can_save"] = accessible_objects(request.user).filter(research_collections=collection, pk__in=ids).count() == len(ids)
    analyses = SavedStudyAnalysis.objects.filter(collection=collection).defer("state", "source_digests", "notes")
    page = Paginator(analyses, ANALYSIS_PAGE_SIZE).get_page(controls.get("analyses_page", "1"))
    result["page"] = page
    navigation = {**state, **controls}
    if page.number > 1:
        context.setdefault("study_return_params", {})["analyses_page"] = str(page.number)
    else:
        context.setdefault("study_return_params", {}).pop("analyses_page", None)
    for item in page:
        result["rows"].append({"id": item.pk, "title": item.title, "updated_at": item.updated_at,
                               "open_url": reverse("collection_analysis_open", args=[collection.pk, item.pk])})
    if page.has_previous():
        result["previous_url"] = base_url + "?" + urlencode({**navigation, "analyses_page": str(page.previous_page_number())})
    if page.has_next():
        result["next_url"] = base_url + "?" + urlencode({**navigation, "analyses_page": str(page.next_page_number())})
    active = None
    if controls.get("analysis"):
        active = SavedStudyAnalysis.objects.filter(collection=collection, pk=int(controls["analysis"])).first()
        if active is None:
            result["error"] = UNAVAILABLE_ANALYSIS
        else:
            changed, unavailable, source_error = False, False, ""
            try:
                saved_state = _canonical_state(active.state)
                with transaction.atomic():
                    owned = _owned_collection(request, collection.pk, lock=True)
                    digests = _source_digests(request.user, owned, saved_state)
                changed = digests != active.source_digests
                result["active_state_json"] = json.dumps(saved_state, ensure_ascii=False)
            except ValueError as exc:
                unavailable, source_error = True, str(exc)
            result["active"] = {
                "id": active.pk, "title": active.title, "notes": active.notes, "revision": active.revision,
                "open_url": reverse("collection_analysis_open", args=[collection.pk, active.pk]),
                "delete_url": reverse("collection_analysis_delete", args=[collection.pk, active.pk]),
                "changed": changed, "unavailable": unavailable, "source_error": source_error,
                "dirty": state != active.state,
            }
    if form is None:
        result["form"] = AnalysisForm(initial={
            "title": active.title if active else "", "notes": active.notes if active else "",
            "analysis_id": active.pk if active else "", "revision": active.revision if active else "",
            "workspace_state": result["state_json"], "intent": "update" if active else "create",
        })
    return result
