"""
Store temporary membership atomically without rewriting Django session snapshots
"""

import re
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import TemporaryGraphSelection


SELECTION_LIFETIME = timedelta(days=7)


def _session_digest(request):
    """
    Bind temporary membership to one authenticated browser without storing its key

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with an established server session.

    Returns
    -------
    str
        Opaque HMAC digest for this owner and session.
    """
    if not request.user.is_authenticated or not request.session.session_key:
        raise Http404("Selection not found.")
    return salted_hmac(
        "pages.temporary-graph-selection", request.session.session_key,
        algorithm="sha256",
    ).hexdigest()


def _entry_ids(entry, user_id):
    """
    Check a stored or legacy entry before returning its member IDs

    Parameters
    ----------
    entry : object
        One selection entry from a bounded bucket or legacy session.
    user_id : int
        Current authenticated owner.

    Returns
    -------
    list of int
        Validated member identifiers, before current record access is checked.
    """
    from .research_collections import _parse_ids

    if not isinstance(entry, dict) or entry.get("owner") != user_id:
        raise Http404("Selection not found.")
    try:
        return _parse_ids([str(value) for value in entry.get("objects", [])])
    except (TypeError, ValueError):
        raise Http404("Selection not found.") from None


def _legacy_entries(request):
    """
    Import valid legacy tokens once when the browser first changes a selection

    Parameters
    ----------
    request : HttpRequest
        Request whose old session may contain selection entries.

    Returns
    -------
    dict
        At most eight entries belonging to the current owner.
    """
    from .research_collections import MAX_TEMPORARY_SELECTIONS, SELECTION_SESSION_KEY

    legacy = request.session.get(SELECTION_SESSION_KEY, {})
    entries = {}
    if not isinstance(legacy, dict):
        return entries
    for order, (token, entry) in enumerate(legacy.items()):
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            continue
        try:
            ids = _entry_ids(entry, request.user.pk)
        except Http404:
            continue
        entries[token] = {"owner": request.user.pk, "objects": ids, "order": order}
        if len(entries) > MAX_TEMPORARY_SELECTIONS:
            entries.pop(next(iter(entries)))
    return entries


def selection_ids(request, token):
    """
    Read the authoritative bucket or an unchanged legacy session without mutation

    Parameters
    ----------
    request : HttpRequest
        Current authenticated browser request.
    token : str
        Temporary selection token from a local link.

    Returns
    -------
    list of int
        Member identifiers whose current access is checked by the caller.
    """
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise Http404("Selection not found.")
    bucket = TemporaryGraphSelection.objects.filter(session_digest=_session_digest(request)).first()
    if bucket is not None:
        if (bucket.owner_id != request.user.pk or bucket.expires_at <= timezone.now()
                or bucket.session_expires_at <= timezone.now()):
            raise Http404("Selection not found.")
        return _entry_ids(bucket.selections.get(token), request.user.pk)
    return _entry_ids(_legacy_entries(request).get(token), request.user.pk)


def _locked_bucket(request, *, allow_create):
    """
    Serialize bucket creation, legacy adoption, eviction and membership updates

    Call this helper inside the transaction that validates and saves membership.
    The owner lock also serializes the first request when no bucket row exists.

    Parameters
    ----------
    request : HttpRequest
        Authenticated mutation request.
    allow_create : bool
        Allow a fresh selection after expiry; appending an expired token fails.

    Returns
    -------
    TemporaryGraphSelection
        Locked bucket with a bounded legacy snapshot only on its first creation.
    """
    digest = _session_digest(request)
    get_user_model().objects.select_for_update(no_key=True).only("pk").get(pk=request.user.pk)
    now = timezone.now()
    bucket = TemporaryGraphSelection.objects.select_for_update().filter(session_digest=digest).first()
    if bucket is not None and bucket.owner_id != request.user.pk:
        raise ValueError("This selection is no longer available. Open Graph and select data again.")
    if bucket is None:
        bucket = TemporaryGraphSelection(
            owner=request.user, session_digest=digest, selections=_legacy_entries(request),
        )
    elif bucket.expires_at <= now or bucket.session_expires_at <= now:
        if not allow_create:
            raise ValueError("This selection has expired. Open Graph and select data again.")
        bucket.selections = {}
    bucket.session_expires_at = request.session.get_expiry_date()
    bucket.expires_at = min(now + SELECTION_LIFETIME, bucket.session_expires_at)
    return bucket


def create_selection(request, ids):
    """
    Create one temporary token after validating its complete accessible membership

    Parameters
    ----------
    request : HttpRequest
        Authenticated selection POST.
    ids : list of int
        Parsed member IDs within the selection limit.

    Returns
    -------
    str
        New token bound to this browser and owner.
    """
    from .research_collections import MAX_TEMPORARY_SELECTIONS, _validate_access

    with transaction.atomic():
        bucket = _locked_bucket(request, allow_create=True)
        _validate_access(request.user, ids, lock=True)
        entries = dict(bucket.selections)
        order = max((entry.get("order", 0) for entry in entries.values()), default=-1) + 1
        while len(entries) >= MAX_TEMPORARY_SELECTIONS:
            oldest = min(entries, key=lambda token: (entries[token].get("order", 0), token))
            entries.pop(oldest)
        token = uuid.uuid4().hex
        entries[token] = {"owner": request.user.pk, "objects": ids, "order": order}
        bucket.selections = entries
        bucket.save()
    return token


def append_selection(request, token, ids):
    """
    Union additions under the database lock and reject the whole invalid request

    Parameters
    ----------
    request : HttpRequest
        Authenticated continuation POST.
    token : str
        Existing temporary selection in this browser.
    ids : list of int
        Parsed requested additions.

    Returns
    -------
    bool
        Whether the complete validated union added at least one member.
    """
    from .research_collections import MAX_SELECTION_OBJECTS, _validate_access

    with transaction.atomic():
        bucket = _locked_bucket(request, allow_create=False)
        try:
            existing = _entry_ids(bucket.selections.get(token), request.user.pk)
        except Http404:
            raise ValueError("This selection is no longer available. Open Graph and select data again.") from None
        combined = list(dict.fromkeys([*existing, *ids]))
        if len(combined) > MAX_SELECTION_OBJECTS:
            raise ValueError(
                f"A temporary selection can contain up to {MAX_SELECTION_OBJECTS} data objects. "
                "Save this selection as a research collection to add more objects."
            )
        _validate_access(request.user, combined, lock=True)
        bucket.selections = {
            **bucket.selections, token: {**bucket.selections[token], "objects": combined},
        }
        bucket.save()
    return len(combined) > len(existing)


def prune_expired_selections():
    """
    Clear expired membership and remove buckets whose server session is gone

    A live session may have renewed its expiry after a bucket became inactive.
    Its empty bucket remains a tombstone so legacy session entries stay expired.

    Returns
    -------
    tuple of int
        Number of buckets cleared and number deleted after checking live sessions.
    """
    cutoff = timezone.now()
    cleared = TemporaryGraphSelection.objects.filter(
        Q(expires_at__lte=cutoff) | Q(session_expires_at__lte=cutoff),
    ).exclude(selections={}).update(selections={})
    live = {
        salted_hmac("pages.temporary-graph-selection", key, algorithm="sha256").hexdigest()
        for key in Session.objects.filter(expire_date__gt=cutoff).values_list("session_key", flat=True).iterator(chunk_size=500)
    }
    removed = 0
    pending = []
    for pk, digest in TemporaryGraphSelection.objects.filter(updated_at__lte=cutoff).values_list(
        "pk", "session_digest",
    ).iterator(chunk_size=200):
        if digest not in live:
            pending.append(pk)
        if len(pending) == 200:
            count, _ = TemporaryGraphSelection.objects.filter(pk__in=pending, updated_at__lte=cutoff).delete()
            removed += count
            pending = []
    if pending:
        count, _ = TemporaryGraphSelection.objects.filter(pk__in=pending, updated_at__lte=cutoff).delete()
        removed += count
    return cleared, removed
