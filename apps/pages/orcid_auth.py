import math
import re
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import AccountProfile


ORCID_TRANSACTION_SESSION_KEY = "orcid_oauth_transaction"

_ORCID_PATTERN = r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]"
_STATE_PATTERN = re.compile(r"[A-Za-z0-9_-]+", flags=re.ASCII)
_TRANSACTION_FIELDS = {
    "state",
    "intent",
    "user_id",
    "created_at",
    "next",
}
_VALID_INTENTS = {"login", "link"}
_TRANSACTION_LIFETIME_SECONDS = 600
_MAX_FUTURE_CLOCK_SKEW_SECONDS = 30
_DEFAULT_NEXT_URL = "/search/"


class ORCIDFlowError(Exception):
    """Report an invalid or unusable ORCID authentication value"""


@dataclass(frozen=True)
class ORCIDTransaction:
    """Represent one consumed ORCID OAuth transaction"""

    state: str
    intent: str
    user_id: int | None
    created_at: float
    next_url: str


def normalize_orcid(value) -> str:
    """Validate and return one canonical ORCID identifier"""
    if not isinstance(value, str) or re.fullmatch(
        _ORCID_PATTERN,
        value,
        flags=re.ASCII,
    ) is None:
        raise ORCIDFlowError("ORCID iD is invalid")

    compact_orcid = value.replace("-", "")
    total = 0
    for digit in compact_orcid[:15]:
        total = (total + int(digit)) * 2

    checksum_value = (12 - total % 11) % 11
    expected_checksum = "X" if checksum_value == 10 else str(checksum_value)
    if compact_orcid[-1] != expected_checksum:
        raise ORCIDFlowError("ORCID iD is invalid")

    return value


def start_orcid_transaction(
    request,
    intent,
    user_id=None,
    next_url="",
) -> str:
    """Create and store one ORCID OAuth transaction"""
    request.session.pop(ORCID_TRANSACTION_SESSION_KEY, None)

    if not isinstance(intent, str) or intent not in _VALID_INTENTS:
        raise ORCIDFlowError("ORCID transaction intent is invalid")
    if user_id is not None and (
        not isinstance(user_id, int) or isinstance(user_id, bool)
    ):
        raise ORCIDFlowError("ORCID transaction user is invalid")

    state = secrets.token_urlsafe(24)
    request.session[ORCID_TRANSACTION_SESSION_KEY] = {
        "state": state,
        "intent": intent,
        "user_id": user_id,
        "created_at": timezone.now().timestamp(),
        "next": _sanitize_next_url(request, next_url),
    }
    return state


def consume_orcid_transaction(request, received_state) -> ORCIDTransaction:
    """Consume and validate one ORCID OAuth transaction"""
    payload = request.session.pop(ORCID_TRANSACTION_SESSION_KEY, None)
    if not isinstance(payload, dict) or set(payload) != _TRANSACTION_FIELDS:
        raise ORCIDFlowError("ORCID transaction is invalid")

    stored_state = payload["state"]
    if (
        not isinstance(stored_state, str)
        or not stored_state
        or _STATE_PATTERN.fullmatch(stored_state) is None
        or not isinstance(received_state, str)
        or not received_state
        or _STATE_PATTERN.fullmatch(received_state) is None
    ):
        raise ORCIDFlowError("ORCID transaction is invalid")
    if not secrets.compare_digest(stored_state, received_state):
        raise ORCIDFlowError("ORCID transaction is invalid")

    intent = payload["intent"]
    user_id = payload["user_id"]
    created_at = payload["created_at"]
    next_url = payload["next"]
    if not isinstance(intent, str) or intent not in _VALID_INTENTS:
        raise ORCIDFlowError("ORCID transaction is invalid")
    if user_id is not None and (
        not isinstance(user_id, int) or isinstance(user_id, bool)
    ):
        raise ORCIDFlowError("ORCID transaction is invalid")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        raise ORCIDFlowError("ORCID transaction is invalid")
    try:
        created_at_value = float(created_at)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ORCIDFlowError("ORCID transaction is invalid") from exc
    if not math.isfinite(created_at_value):
        raise ORCIDFlowError("ORCID transaction is invalid")
    if not isinstance(next_url, str) or not next_url:
        raise ORCIDFlowError("ORCID transaction is invalid")
    next_url = _sanitize_next_url(request, next_url)

    age = timezone.now().timestamp() - created_at_value
    if (
        age > _TRANSACTION_LIFETIME_SECONDS
        or age < -_MAX_FUTURE_CLOCK_SKEW_SECONDS
    ):
        raise ORCIDFlowError("ORCID transaction has expired")

    return ORCIDTransaction(
        state=stored_state,
        intent=intent,
        user_id=user_id,
        created_at=created_at_value,
        next_url=next_url,
    )


def complete_orcid_login(request, orcid, next_url) -> HttpResponse:
    """
    Resolve a verified ORCID identity into one safe local login

    Recheck the resolved binding while holding the same locks as disconnect.

    Parameters
    ----------
    request : HttpRequest
        Callback request with the browser's real session.
    orcid : str
        Canonical verified ORCID identity.
    next_url : str
        Sanitized local redirect from the consumed transaction.

    Returns
    -------
    HttpResponse
        Local redirect after login or a controlled refusal.
    """
    identity_profile = (
        AccountProfile.objects.select_related("user")
        .filter(authenticated_orcid=orcid)
        .first()
    )

    if request.user.is_authenticated:
        if (
            identity_profile is not None
            and identity_profile.user_id == request.user.pk
            and request.user.is_active
            and identity_profile.user.is_active
        ):
            messages.success(request, "Signed in with ORCID.")
            return redirect(next_url)

        messages.error(
            request,
            (
                "This ORCID iD is not connected to your signed-in account. "
                "Use Connect ORCID in account settings."
            ),
        )
        return redirect("account_settings")

    if identity_profile is not None:
        user = identity_profile.user
        if not user.is_active:
            messages.error(
                request,
                (
                    "ORCID sign in could not be completed. Sign in locally "
                    "and use Connect ORCID in account settings."
                ),
            )
            return redirect(settings.LOGIN_URL)
    else:
        legacy_claim_exists = AccountProfile.objects.filter(orcid=orcid).exists()
        if legacy_claim_exists:
            messages.error(
                request,
                (
                    "ORCID sign in could not be completed. Sign in locally "
                    "and use Connect ORCID in account settings."
                ),
            )
            return redirect(settings.LOGIN_URL)

        try:
            user = _create_orcid_user(orcid)
        except IntegrityError:
            identity_profile = (
                AccountProfile.objects.select_related("user")
                .filter(authenticated_orcid=orcid)
                .first()
            )
            if identity_profile is None or not identity_profile.user.is_active:
                messages.error(
                    request,
                    "ORCID sign in could not be completed. Please try again.",
                )
                return redirect(settings.LOGIN_URL)
            user = identity_profile.user

    with transaction.atomic():
        current_user = User.objects.select_for_update().filter(pk=user.pk).first()
        if (
            current_user is None
            or not current_user.is_active
            or not AccountProfile.objects.select_for_update().filter(
                user_id=current_user.pk,
                authenticated_orcid=orcid,
            ).exists()
        ):
            messages.error(
                request,
                "ORCID sign in could not be completed. Please try again.",
            )
            return redirect(settings.LOGIN_URL)

        login(request, current_user)
    messages.success(request, "Signed in with ORCID.")
    return redirect(next_url)


def complete_orcid_link(request, orcid_transaction, orcid) -> HttpResponse:
    """
    Link one verified ORCID identity to its initiating local account

    Disconnect markers prevent older callbacks from restoring a removed link.

    Parameters
    ----------
    request : HttpRequest
        Callback request carrying the initiating account's session.
    orcid_transaction : ORCIDTransaction
        Consumed transaction bound to the initiating account and start time.
    orcid : str
        Canonical verified ORCID identity returned by the provider.

    Returns
    -------
    HttpResponse
        Redirect to account settings with the connection result.
    """
    if (
        not request.user.is_authenticated
        or not request.user.is_active
        or not isinstance(orcid_transaction, ORCIDTransaction)
        or orcid_transaction.intent != "link"
        or orcid_transaction.user_id != request.user.pk
    ):
        messages.error(
            request,
            "ORCID account linking could not be completed.",
        )
        return redirect("account_settings")

    try:
        with transaction.atomic():
            current_user = User.objects.select_for_update().get(pk=request.user.pk)
            if not current_user.is_active:
                messages.error(
                    request,
                    "ORCID account linking could not be completed.",
                )
                return redirect("account_settings")

            current_profile, _created = (
                AccountProfile.objects.select_for_update().get_or_create(
                    user=current_user
                )
            )
            if (
                current_profile.orcid_disconnected_at is not None
                and orcid_transaction.created_at
                <= current_profile.orcid_disconnected_at.timestamp()
            ):
                messages.error(
                    request,
                    "ORCID account linking could not be completed. Start a new connection.",
                )
                return redirect("account_settings")
            if current_profile.authenticated_orcid == orcid:
                messages.success(request, "ORCID iD connected.")
                return redirect("account_settings")
            if current_profile.authenticated_orcid is not None:
                messages.error(
                    request,
                    "ORCID account linking could not be completed.",
                )
                return redirect("account_settings")

            identity_owner = (
                AccountProfile.objects.select_for_update()
                .filter(authenticated_orcid=orcid)
                .first()
            )
            if identity_owner is not None:
                messages.error(
                    request,
                    "This ORCID iD is already connected to another account. "
                    "Please sign in to that account and disconnect it in Settings "
                    "before connecting it here.",
                )
                return redirect("account_settings")

            current_profile.authenticated_orcid = orcid
            current_profile.orcid_authenticated_at = timezone.now()
            current_profile.save(
                update_fields=[
                    "authenticated_orcid",
                    "orcid_authenticated_at",
                ]
            )
    except (IntegrityError, User.DoesNotExist):
        messages.error(
            request,
            "ORCID account linking could not be completed.",
        )
        return redirect("account_settings")

    messages.success(request, "ORCID iD connected.")
    return redirect("account_settings")


def _create_orcid_user(orcid) -> User:
    """
    Atomically create one ordinary account for a verified identity

    Parameters
    ----------
    orcid : str
        Canonical verified ORCID identity.

    Returns
    -------
    User
        Newly created local account.

    Raises
    ------
    IntegrityError
        The identity or selected username was claimed concurrently.
    """
    compact_orcid = orcid.replace("-", "")
    base_username = f"orcid_{compact_orcid}"

    with transaction.atomic():
        username = base_username
        suffix = 2
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{suffix}"
            suffix += 1

        user = User(
            username=username,
            first_name="",
            last_name="",
            email="",
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        user.set_unusable_password()
        user.save(force_insert=True)
        AccountProfile.objects.create(
            user=user,
            authenticated_orcid=orcid,
            orcid_authenticated_at=timezone.now(),
        )

    return user


def _sanitize_next_url(request, next_url) -> str:
    """Return a safe same-host next target or the search default"""
    if (
        not isinstance(next_url, str)
        or not next_url
        or next_url.startswith("//")
        or "\\" in next_url
    ):
        return _DEFAULT_NEXT_URL

    allowed_hosts = {request.get_host()}
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts=allowed_hosts,
        require_https=not settings.DEBUG,
    ):
        return next_url

    return _DEFAULT_NEXT_URL
