"""
Extract collection discovery metadata without retaining the source arrays
"""

import json
import re
from urllib.parse import unquote, urlsplit

from apps.dyn_api.metadata_compat import field_name, field_value, metadata_view
from .study_comparison import SUMMARY_VERSION, build_study_projection


DOI = re.compile(r"10\.\d{4,9}/\S+\Z", re.IGNORECASE)


def _names(value, fallback_keys=()):
    """
    Collect supplied text without turning identifiers or arbitrary objects into names

    Parameters
    ----------
    value : object
        A recognized metadata value.
    fallback_keys : tuple, optional
        Explicit name fields, in their preferred order.

    Returns
    -------
    list of str
        Distinct labels in supplied order, ignoring case and surrounding spaces.
    """
    names = {}
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and item.strip():
            label = item.strip()
            names.setdefault(label.casefold(), label)
        elif isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, dict):
            for key in fallback_keys:
                labels = _names(field_value(item, key))
                if labels:
                    pending.extend(reversed(labels))
                    break
    return list(names.values())


def _reference_key(label):
    """
    Recognize explicit DOI forms while keeping other reference text exact

    Parameters
    ----------
    label : str
        A nonempty supplied relation string.

    Returns
    -------
    str
        Comparable DOI identity or the unchanged reference text.
    """
    candidate = label
    if candidate.lower().startswith("doi:"):
        candidate = candidate[4:].strip()
    elif candidate.lower().startswith(("http://", "https://")):
        try:
            url = urlsplit(candidate)
        except ValueError:
            return "text:" + label
        if url.netloc.lower() not in {"doi.org", "dx.doi.org"} or url.query or url.fragment:
            return "text:" + label
        try:
            candidate = unquote(url.path.lstrip("/"), errors="strict")
        except UnicodeDecodeError:
            return "text:" + label
    if DOI.fullmatch(candidate):
        return "doi:" + candidate.casefold()
    return "text:" + label


def _relations(value):
    """
    Retain explicit reference strings without searching nested metadata

    Parameters
    ----------
    value : object
        The record's recognized top level relation field.

    Returns
    -------
    dict
        Comparable reference keys and their first supplied spelling.
    """
    references = {}
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, str) and item.strip():
            label = item.strip()
            references.setdefault(_reference_key(label), label)
    return references


def _version_text(value):
    """
    Preserve recorded textual and numeric software versions for comparison

    Parameters
    ----------
    value : object
        Supplied software version or descriptive values in their stored order.

    Returns
    -------
    str
        Complete scalar versions without interpreting numbers as software names.
    """
    versions = []
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
            continue
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, (int, float, bool)):
            text = json.dumps(item)
        else:
            continue
        if text and text not in versions:
            versions.append(text)
    return "; ".join(versions)


def build_collection_summary(raw_data):
    """
    Extract supplied collection labels without retaining raw mechanical arrays

    Parameters
    ----------
    raw_data : object
        Original JSON metadata whose keys and values remain unchanged.

    Returns
    -------
    dict
        Scalar descriptions and label groups, without retained raw metadata.
    """
    conflicts = []
    data = metadata_view(raw_data, conflicts=conflicts)
    comparison = build_study_projection(data, conflicts, original=raw_data)
    for first, second in conflicts:
        for field in ("identifier", "relation", "phase", "mechanical_BC"):
            if field_name(first) == field_name(field) or field_name(second) == field_name(field):
                data.pop(field, None)
        if first.startswith("mechanical_BC[") or first.startswith("mechanical_BC."):
            data.pop("mechanical_BC", None)
    software = _names(data.get("software"), ("name", "software_name"))
    phases = _names(data.get("phase"), ("phase_name", "phase_identifier", "name", "identifier"))
    references = _relations(data.get("relation"))
    loading = []
    conditions = data.get("mechanical_BC", [])
    if not isinstance(conditions, list):
        conditions = [conditions]
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        label = " · ".join(filter(None, (
            "; ".join(_names(condition.get("loading_type"))),
            "; ".join(_names(condition.get("loading_mode"))),
        )))
        if label and label not in loading:
            loading.append(label)
    identifier = "; ".join(_names(data.get("identifier")))
    title = "; ".join(_names(data.get("title"))) or identifier or "Untitled data object"
    return {
        "summary_version": SUMMARY_VERSION, "comparison": comparison,
        "title": title, "identifier": identifier,
        "software": "; ".join(software),
        "software_version": _version_text(data.get("software_version")),
        "phase": "; ".join(phases), "loading": "; ".join(loading),
        "creator": "; ".join(_names(data.get("creator"), ("name", "creator_name"))),
        "relations": "; ".join(references.values()),
        "groups": {
            "relations": references,
            "software": {name.casefold(): name for name in software},
            "phase": {name.casefold(): name for name in phases},
        },
    }
