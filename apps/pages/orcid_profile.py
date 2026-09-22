import calendar
import json
import logging
from datetime import date

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, transaction
from django.utils import timezone

from .models import AccountProfile


logger = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 512 * 1024
_PUBLIC_API_URLS = {
    "https://orcid.org": "https://pub.orcid.org/v3.0",
    "https://sandbox.orcid.org": "https://pub.sandbox.orcid.org/v3.0",
}


def _read_section(api_url, orcid, section, access_token):
    """
    Read one bounded public section without following redirects or retrying

    Parameters
    ----------
    api_url : str
        Public API URL selected from the supported ORCID environments.
    orcid : str
        Verified identifier belonging to the signed in account.
    section : str
        Email or employment endpoint to read.
    access_token : str
        Token returned by this OAuth exchange, used only for this request.

    Returns
    -------
    dict
        Parsed section, or an empty mapping when unavailable.
    """
    try:
        with requests.get(
            f"{api_url}/{orcid}/{section}",
            headers={
                "Accept": "application/vnd.orcid+json",
                "Authorization": f"Bearer {access_token}",
            },
            timeout=(2, 3),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                return {}
            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    return {}
            data = json.loads(body)
            return data if isinstance(data, dict) else {}
    except (requests.RequestException, ValueError, RecursionError):
        return {}


def _public_email(data):
    """
    Select a verified public email with preference for the primary address

    Parameters
    ----------
    data : dict
        ORCID email section.

    Returns
    -------
    str
        Valid address that fits the local user field, or an empty string.
    """
    emails = data.get("email")
    if not isinstance(emails, list):
        return ""
    fallback = ""
    for item in emails:
        if not isinstance(item, dict) or item.get("verified") is not True:
            continue
        if item.get("visibility") not in ("public", "PUBLIC"):
            continue
        value = item.get("email")
        if not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) > User._meta.get_field("email").max_length:
            continue
        try:
            validate_email(value)
        except ValidationError:
            continue
        if item.get("primary") is True:
            return value
        if not fallback:
            fallback = value
    return fallback


def _date_bound(value, end=False):
    """
    Interpret a partial affiliation date at the relevant calendar boundary

    Parameters
    ----------
    value : dict or None
        ORCID year, month and day components.
    end : bool
        Use the end of an unspecified month or year for an end date.

    Returns
    -------
    date or None
        Calendar bound, or no bound when the date is absent.

    Raises
    ------
    ValueError
        If present date components cannot describe a calendar date.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid affiliation date")
    parts = {}
    for key in ("year", "month", "day"):
        component = value.get(key)
        if component is None:
            continue
        if not isinstance(component, dict):
            raise ValueError("Invalid affiliation date")
        number = component.get("value")
        if not isinstance(number, str) or not number.isascii() or not number.isdecimal():
            raise ValueError("Invalid affiliation date")
        parts[key] = int(number)
    if "year" not in parts:
        raise ValueError("Affiliation date has no year")
    year = parts["year"]
    month = parts.get("month", 12 if end else 1)
    last_day = calendar.monthrange(year, month)[1] if end else 1
    return date(year, month, parts.get("day", last_day))


def _current_institution(data):
    """
    Select one distinct current public employer without guessing between them

    Parameters
    ----------
    data : dict
        ORCID version 3 employment affiliation groups.

    Returns
    -------
    str
        Unambiguous current institution, or an empty string for manual entry.
    """
    groups = data.get("affiliation-group")
    if not isinstance(groups, list):
        return ""
    institutions = {}
    today = timezone.localdate()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("summaries"), list):
            continue
        for summary in group["summaries"]:
            if not isinstance(summary, dict):
                continue
            item = summary.get("employment-summary")
            if not isinstance(item, dict) or item.get("visibility") not in ("public", "PUBLIC"):
                continue
            try:
                start = _date_bound(item.get("start-date"))
                end = _date_bound(item.get("end-date"), end=True)
            except (ValueError, OverflowError):
                continue
            if (start and start > today) or (end and end < today):
                continue
            organization = item.get("organization")
            if not isinstance(organization, dict):
                continue
            name = organization.get("name")
            if not isinstance(name, str):
                continue
            name = " ".join(name.split())
            if not name or "\x00" in name or len(name) > AccountProfile._meta.get_field("institution").max_length:
                continue
            institutions.setdefault(name.casefold(), name)
    return next(iter(institutions.values())) if len(institutions) == 1 else ""


def fill_missing_orcid_profile(user_id, orcid, access_token):
    """
    Fill blank email and institution fields after successful ORCID authentication

    Perform optional network reads outside database locks, then recheck the
    identity and current field values before writing. Never store the token.

    Parameters
    ----------
    user_id : int
        Local account resolved or linked by the completed OAuth flow.
    orcid : str
        Verified identifier attached to that account.
    access_token : str or None
        Token available only during this callback.
    """
    if not access_token:
        return
    api_url = _PUBLIC_API_URLS.get(settings.ORCID_BASE_URL.rstrip("/"))
    if api_url is None:
        return
    try:
        profile = AccountProfile.objects.select_related("user").filter(
            user_id=user_id, authenticated_orcid=orcid, user__is_active=True
        ).first()
        if profile is None:
            return
        email = ""
        institution = ""
        if not profile.user.email.strip():
            email = _public_email(_read_section(api_url, orcid, "email", access_token))
        if not profile.institution.strip():
            institution = _current_institution(
                _read_section(api_url, orcid, "employments", access_token)
            )
        if not email and not institution:
            return

        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=user_id, is_active=True).first()
            if user is None:
                return
            current_profile = AccountProfile.objects.select_for_update().filter(
                pk=profile.pk,
                authenticated_orcid=orcid,
                orcid_disconnected_at=profile.orcid_disconnected_at,
            ).first()
            if current_profile is None:
                return
            if email and not user.email.strip():
                user.email = email
                user.save(update_fields=["email"])
            if institution and not current_profile.institution.strip():
                current_profile.institution = institution
                current_profile.save(update_fields=["institution"])
    except DatabaseError:
        logger.warning("Could not save optional ORCID profile details")
