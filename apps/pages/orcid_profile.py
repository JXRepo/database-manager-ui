import calendar
import json
import logging
from datetime import date

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
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
        Person or employment endpoint to read.
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
    if not isinstance(data, dict):
        return ""
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


def _profile_text(value, field):
    """
    Normalize provider text that fits an optional profile field

    Parameters
    ----------
    value : object
        Provider value before type and length checks.
    field : str
        Destination field on the account profile.

    Returns
    -------
    str
        Normalized text, or an empty string when unusable.
    """
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    if "\x00" in value or len(value) > AccountProfile._meta.get_field(field).max_length:
        return ""
    return value


def _public_items(data, section, key):
    """
    Read public person items in the order chosen by the researcher

    Parameters
    ----------
    data : dict
        ORCID person response.
    section : str
        Container for the requested items.
    key : str
        List key within that container.

    Returns
    -------
    list of dict
        Public items ordered by descending display index, with stable ties.
    """
    container = data.get(section)
    if not isinstance(container, dict) or not isinstance(container.get(key), list):
        return []
    ranked = []
    for item in container[key]:
        if not isinstance(item, dict) or item.get("visibility") not in ("public", "PUBLIC"):
            continue
        index = item.get("display-index", 0)
        try:
            index = int(index) if isinstance(index, (int, str)) else 0
        except ValueError:
            index = 0
        ranked.append((index, item))
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return [item for _index, item in ranked]


def _public_person(data):
    """
    Extract a public name, preferred website and research keywords

    Parameters
    ----------
    data : dict
        ORCID person response, including per item visibility.

    Returns
    -------
    dict
        Optional account profile values that pass local validation.
    """
    values = {}
    name = data.get("name")
    if isinstance(name, dict) and name.get("visibility") in ("public", "PUBLIC"):
        parts = {}
        for key in ("credit-name", "given-names", "family-name"):
            part = name.get(key)
            parts[key] = _profile_text(part.get("value"), "display_name") if isinstance(part, dict) else ""
        full_name = " ".join(part for part in (parts["given-names"], parts["family-name"]) if part)
        values["display_name"] = parts["credit-name"] or _profile_text(full_name, "display_name")

    for item in _public_items(data, "researcher-urls", "researcher-url"):
        url = item.get("url")
        if not isinstance(url, dict):
            continue
        website = _profile_text(url.get("value"), "website")
        try:
            URLValidator(schemes=["http", "https"])(website)
        except ValidationError:
            continue
        values["website"] = website
        break

    keywords = []
    seen = set()
    for item in _public_items(data, "keywords", "keyword"):
        keyword = _profile_text(item.get("content"), "research_keywords")
        if not keyword or keyword.casefold() in seen:
            continue
        keywords.append(keyword)
        seen.add(keyword.casefold())
    values["research_keywords"] = _profile_text(
        ", ".join(keywords), "research_keywords"
    )
    return values


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


def _current_employment(data, profile):
    """
    Select compatible details from one unambiguous current public employment

    Parameters
    ----------
    data : dict
        ORCID version 3 employment affiliation groups.
    profile : AccountProfile
        Locked current profile whose manual affiliation values must be respected.

    Returns
    -------
    dict
        Institution and any unambiguous matching department and position.
    """
    groups = data.get("affiliation-group")
    if not isinstance(groups, list):
        return {}
    institutions = {}
    existing_institution = " ".join(profile.institution.split()).casefold()
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
            name = _profile_text(organization.get("name"), "institution")
            if not name or (existing_institution and name.casefold() != existing_institution):
                continue
            values = {
                "institution": name,
                "department": _profile_text(item.get("department-name"), "department"),
                "position": _profile_text(item.get("role-title"), "position"),
            }
            institutions.setdefault(name.casefold(), []).append(values)
    if len(institutions) != 1:
        return {}
    employments = next(iter(institutions.values()))
    compatible = {}
    for values in employments:
        if any(
            getattr(profile, field).strip()
            and " ".join(getattr(profile, field).split()).casefold() != values[field].casefold()
            for field in ("department", "position")
        ):
            continue
        pair = (values["department"].casefold(), values["position"].casefold())
        compatible.setdefault(pair, values)
    if not compatible:
        return {}
    if len(compatible) == 1:
        return next(iter(compatible.values()))
    return {"institution": employments[0]["institution"]}


def fill_missing_orcid_profile(user_id, orcid, access_token):
    """
    Fill blank account details after successful ORCID authentication

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
        person = {}
        employment = {}
        if not profile.user.email.strip() or any(
            not getattr(profile, field).strip()
            for field in ("display_name", "website", "research_keywords")
        ):
            person = _read_section(api_url, orcid, "person", access_token)
        if any(
            not getattr(profile, field).strip()
            for field in ("institution", "department", "position")
        ):
            employment = _read_section(api_url, orcid, "employments", access_token)
        email = _public_email(person.get("emails"))
        values = _public_person(person)
        if not email and not any(values.values()) and not employment:
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
            values.update(_current_employment(employment, current_profile))
            changed = []
            for field, value in values.items():
                if value and not getattr(current_profile, field).strip():
                    setattr(current_profile, field, value)
                    changed.append(field)
            if changed:
                current_profile.save(update_fields=changed)
    except DatabaseError:
        logger.warning("Could not save optional ORCID profile details")
