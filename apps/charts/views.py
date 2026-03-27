import json
from collections import Counter
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.pages.models import JSONData


def _normalize_text(value, default="Unknown"):
    """
    Convert a metadata value into a short text label
    """
    if value is None or value == "" or value == []:
        return default

    if isinstance(value, str):
        text = value.strip()
        return text if text else default

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                text = (
                    item.get("name")
                    or item.get("creator_name")
                    or item.get("author")
                    or item.get("identifier")
                    or item.get("title")
                    or ""
                )
                text = str(text).strip()
            else:
                text = str(item).strip()

            if text:
                parts.append(text)

        if not parts:
            return default

        return ", ".join(parts)

    if isinstance(value, dict):
        text = (
            value.get("name")
            or value.get("creator_name")
            or value.get("author")
            or value.get("identifier")
            or value.get("title")
            or ""
        )
        text = str(text).strip()
        return text if text else default

    text = str(value).strip()
    return text if text else default


def _extract_keywords(value):
    """
    Extract keyword strings from metadata
    """
    if value is None or value == "" or value == []:
        return []

    if isinstance(value, list):
        keywords = []
        for item in value:
            text = str(item).strip()
            if text:
                keywords.append(text)
        return keywords

    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    text = str(value).strip()
    return [text] if text else []


def _has_shared_users(data):
    """
    Return True when a record has explicit non-public sharing information
    """
    shared_with = data.get("shared_with", [])

    if not isinstance(shared_with, list) or len(shared_with) == 0:
        return False

    for item in shared_with:
        if isinstance(item, dict) and item.get("access_type") == "all":
            continue
        return True

    return False


@login_required
def index(request):
    """
    Display platform-level charts for JSON data objects
    """
    data_objects = list(JSONData.objects.select_related("owner").all())

    public_count = 0
    shared_count = 0
    private_count = 0

    software_counter = Counter()
    keyword_counter = Counter()

    end_date = timezone.localdate()
    trend_days = 30
    start_date = end_date - timedelta(days=trend_days - 1)
    date_points = [start_date + timedelta(days=offset) for offset in range(trend_days)]
    upload_counter = Counter()

    for obj in data_objects:
        data = obj.data or {}

        if obj.access_type == "all":
            public_count += 1
        elif _has_shared_users(data):
            shared_count += 1
        else:
            private_count += 1

        software_name = _normalize_text(data.get("software"), default="Unknown")
        software_counter[software_name] += 1

        for keyword in _extract_keywords(data.get("keywords")):
            keyword_counter[keyword] += 1

        uploaded_date = timezone.localtime(obj.uploaded_at).date()
        if start_date <= uploaded_date <= end_date:
            upload_counter[uploaded_date] += 1

    access_labels = ["Public", "Shared", "Private"]
    access_series = [public_count, shared_count, private_count]

    upload_labels = [point.strftime("%Y-%m-%d") for point in date_points]
    upload_series = [upload_counter.get(point, 0) for point in date_points]

    top_software = software_counter.most_common(10)
    software_labels = [item[0] for item in top_software]
    software_series = [item[1] for item in top_software]

    top_keywords = keyword_counter.most_common(10)
    keyword_labels = [item[0] for item in top_keywords]
    keyword_series = [item[1] for item in top_keywords]

    context = {
        "segment": "charts",
        "total_objects": len(data_objects),
        "access_labels_json": json.dumps(access_labels),
        "access_series_json": json.dumps(access_series),
        "upload_labels_json": json.dumps(upload_labels),
        "upload_series_json": json.dumps(upload_series),
        "software_labels_json": json.dumps(software_labels),
        "software_series_json": json.dumps(software_series),
        "keyword_labels_json": json.dumps(keyword_labels),
        "keyword_series_json": json.dumps(keyword_series),
    }
    return render(request, "charts/index.html", context)