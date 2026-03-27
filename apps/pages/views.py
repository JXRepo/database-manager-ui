import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from apps.pages.models import Product
from django.core import serializers
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import *
from .forms import SignUpForm, JSONUploadForm
from apps.dyn_api.helpers import validate_json
from numbers import Number


@login_required
def index(request):
    """Redirect authenticated users to the search page"""
    return redirect("search")

# Components
def color(request):
  context = {
    'segment': 'color'
  }
  return render(request, "pages/color.html", context)

def typography(request):
  context = {
    'segment': 'typography'
  }
  return render(request, "pages/typography.html", context)

def icon_feather(request):
  context = {
    'segment': 'feather_icon'
  }
  return render(request, "pages/icon-feather.html", context)

def sample_page(request):
  context = {
    'segment': 'sample_page',
  }
  return render(request, 'pages/sample-page.html', context)


def register_view(request):
  """Register a new user and log them in"""
  if request.method == "POST":
    form = SignUpForm(request.POST)
    if form.is_valid():
      user = form.save()
      login(request, user)
      return redirect("search")
  else:
    form = SignUpForm()

  return render(request, "accounts/register.html", {"form": form})


@login_required
def upload_json_view(request):
    """
    Upload a JSON file, validate data objects, and save valid objects to the database

    Parameters
    ----------
    request : HttpRequest
        Incoming HTTP request

    Returns
    -------
    HttpResponse
        Rendered upload page or redirect after success
    """
    if request.method == "POST":
        form = JSONUploadForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]

            try:
                payload = json.load(uploaded_file)
            except json.JSONDecodeError:
                messages.error(request, "Invalid JSON file")
                return render(request, "pages/upload.html", {"form": form})

            if isinstance(payload, list):
                objects = payload
            elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
                objects = payload["data"]
            else:
                messages.error(
                    request,
                    "JSON must be either a list or a dict with a 'data' list",
                )
                return render(request, "pages/upload.html", {"form": form})

            valid_objects, errors = validate_json(objects)

            for error in errors:
                messages.error(request, error)

            created_count = 0

            for obj in valid_objects:
                shared_with = obj.get("shared_with", [])
                access_type = "c"

                for item in shared_with:
                    if isinstance(item, dict) and item.get("access_type") == "all":
                        access_type = "all"
                        break

                if access_type not in {"c", "all"}:
                    access_type = "c"

                JSONData.objects.create(
                    owner=request.user,
                    data=obj,
                    access_type=access_type,
                )
                created_count += 1

            if created_count > 0:
                messages.success(
                    request,
                    f"Upload successful: {created_count} objects saved",
                )

            if created_count == 0 and errors:
                messages.error(request, "No valid objects were saved")

            return redirect("upload_json")

    else:
        form = JSONUploadForm()

    return render(request, "pages/upload.html", {"form": form})


def _format_summary_value(value):
    """
    Convert a JSON value into a short display string
    """
    if value is None or value == "" or value == []:
        return "-"

    if isinstance(value, list):
        formatted_items = []
        for item in value[:3]:
            if isinstance(item, dict):
                formatted_items.append(
                    item.get("name")
                    or item.get("creator_name")
                    or item.get("author")
                    or str(item)
                )
            else:
                formatted_items.append(str(item))

        text = ", ".join(formatted_items)
        if len(value) > 3:
            text += " ..."
        return text

    if isinstance(value, dict):
        return value.get("name") or value.get("identifier") or str(value)

    return str(value)


def _build_summary_fields(data):
    """
    Build the summary field list for the accordion preview
    """
    summary_config = [
        ("Identifier", "identifier"),
        ("Creator", "creator"),
        ("Created Date", "date"),
        ("Software", "software"),
        ("Keywords", "keywords"),
    ]

    fields = []
    for label, key in summary_config:
        raw_value = data.get(key)

        if label == "Keywords":
            if isinstance(raw_value, list):
                tags = [str(item).strip() for item in raw_value if str(item).strip()]
            elif raw_value:
                tags = [item.strip() for item in str(raw_value).split(",") if item.strip()]
            else:
                tags = []

            fields.append(
                {
                    "label": label,
                    "value": tags,
                    "type": "keywords",
                }
            )
        else:
            if key in data:
                fields.append(
                    {
                        "label": label,
                        "value": _format_summary_value(raw_value),
                    }
                )

    return fields[:6]



def _normalize_search_value(value):
    """
    Convert nested JSON values into searchable text
    """
    if value is None or value == "" or value == []:
        return ""

    if isinstance(value, str):
        return value.strip()

    if _is_number_value(value):
        return str(value)

    if isinstance(value, list):
        parts = [_normalize_search_value(item) for item in value]
        return " ".join(part for part in parts if part)

    if isinstance(value, dict):
        preferred_keys = (
            "name",
            "creator_name",
            "author",
            "identifier",
            "title",
            "label",
            "value",
        )

        parts = []
        for key in preferred_keys:
            if key in value:
                text = _normalize_search_value(value.get(key))
                if text:
                    parts.append(text)

        if not parts:
            parts = [_normalize_search_value(item) for item in value.values()]

        return " ".join(part for part in parts if part)

    return str(value)


def _build_search_text(obj, field):
    """
    Build searchable text for one JSON data object
    """
    data = obj.data or {}
    access_text = "public all shared" if obj.access_type == "all" else "private c"

    field_map = {
        "title": data.get("title", ""),
        "identifier": data.get("identifier", ""),
        "creator": data.get("creator", ""),
        "date": data.get("date", ""),
        "software": data.get("software", ""),
        "keywords": data.get("keywords", ""),
        "access": access_text,
        "all": [
            data.get("title", ""),
            data.get("identifier", ""),
            data.get("creator", ""),
            data.get("date", ""),
            data.get("software", ""),
            data.get("keywords", ""),
            access_text,
        ],
    }

    return _normalize_search_value(field_map.get(field, ""))


def _prepare_list_object(obj):
    """
    Attach summary fields to one data object
    """
    data = obj.data or {}
    summary_fields = _build_summary_fields(data)

    access_display = "Public" if obj.access_type == "all" else "Private"
    summary_fields.append(
        {
            "label": "Access",
            "value": access_display,
            "type": "access",
        }
    )

    obj.summary_fields = summary_fields
    return obj


def _is_shared_with_user(data, user):
    """
    Return True when the JSON object is explicitly shared with the user
    """
    shared_with = data.get("shared_with", [])

    if not isinstance(shared_with, list):
        return False

    username = (user.username or "").strip().casefold()
    email = (user.email or "").strip().casefold()

    for item in shared_with:
        if not isinstance(item, dict):
            continue

        candidates = [
            str(item.get("username", "")).strip().casefold(),
            str(item.get("user", "")).strip().casefold(),
            str(item.get("name", "")).strip().casefold(),
            str(item.get("email", "")).strip().casefold(),
        ]

        if username and username in candidates:
            return True

        if email and email in candidates:
            return True

    return False


def _user_can_access_object(obj, user):
    """
    Return True when the user is allowed to access this object
    """
    if obj.owner_id == user.id:
        return True

    if obj.access_type == "all":
        return True

    return _is_shared_with_user(obj.data or {}, user)







@login_required
def json_data_list_view(request):
    """
    Display uploaded JSON data objects for the current user
    """
    data_objects = JSONData.objects.filter(owner=request.user).order_by("-uploaded_at")
    prepared_objects = [_prepare_list_object(obj) for obj in data_objects]

    context = {
        "segment": "data_list",
        "data_objects": prepared_objects,
    }
    return render(request, "pages/data_list.html", context)


@login_required
def search_view(request):
    """
    Display the dedicated advanced global search page
    """
    keyword = request.GET.get("keyword", "").strip()
    title = request.GET.get("title", "").strip()
    identifier = request.GET.get("identifier", "").strip()
    creator = request.GET.get("creator", "").strip()
    software = request.GET.get("software", "").strip()
    keywords_value = request.GET.get("keywords", "").strip()
    owner_name = request.GET.get("owner", "").strip()
    access = request.GET.get("access", "").strip()

    search_performed = any(
        [
            keyword,
            title,
            identifier,
            creator,
            software,
            keywords_value,
            owner_name,
            access,
        ]
    )

    filtered_objects = []

    if search_performed:
        data_objects = JSONData.objects.select_related("owner").order_by("-uploaded_at")

        for obj in data_objects:
            if not _user_can_access_object(obj, request.user):
                continue

            data = obj.data or {}

            title_text = _normalize_search_value(data.get("title", ""))
            identifier_text = _normalize_search_value(data.get("identifier", ""))
            creator_text = _normalize_search_value(data.get("creator", ""))
            software_text = _normalize_search_value(data.get("software", ""))
            keywords_text = _normalize_search_value(data.get("keywords", ""))
            owner_text = _normalize_search_value(obj.owner.username)

            if obj.owner_id == request.user.id and obj.access_type == "c":
                access_text = "my private"
            elif obj.access_type == "all":
                access_text = "public"
            else:
                access_text = "shared"

            full_text = " ".join(
                [
                    title_text,
                    identifier_text,
                    creator_text,
                    software_text,
                    keywords_text,
                    owner_text,
                    access_text,
                ]
            ).casefold()

            if keyword and keyword.casefold() not in full_text:
                continue

            if title and title.casefold() not in title_text.casefold():
                continue

            if identifier and identifier.casefold() not in identifier_text.casefold():
                continue

            if creator and creator.casefold() not in creator_text.casefold():
                continue

            if software and software.casefold() not in software_text.casefold():
                continue

            if keywords_value and keywords_value.casefold() not in keywords_text.casefold():
                continue

            if owner_name and owner_name.casefold() not in owner_text.casefold():
                continue

            if access == "public" and obj.access_type != "all":
                continue

            if access == "my_private":
                if not (obj.owner_id == request.user.id and obj.access_type == "c"):
                    continue

            filtered_objects.append(_prepare_list_object(obj))

    context = {
        "segment": "search",
        "data_objects": filtered_objects,
        "search_performed": search_performed,
        "keyword": keyword,
        "title": title,
        "identifier": identifier,
        "creator": creator,
        "software": software,
        "keywords_value": keywords_value,
        "owner_name": owner_name,
        "access": access,
    }
    return render(request, "pages/search.html", context)



def _is_number_value(value):
    """
    Return True when value is a numeric type but not bool
    """
    return isinstance(value, Number) and not isinstance(value, bool)


def _is_numeric_list(value):
    """
    Return True when value is a non-empty list containing only numeric values
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(_is_number_value(item) for item in value)
    )




def _format_detail_label(path):
    """
    Format a detail label without changing original field names
    """
    parts = []

    for raw_part in path.split("."):
        clean_part = raw_part.split("[")[0].strip()
        clean_part = clean_part.lstrip("$")

        if clean_part:
            parts.append(clean_part)

    return " / ".join(parts)






def _build_detail_rows(data, prefix=""):
    """
    Recursively build detail rows while preserving the original JSON order

    Rules
    -----
    - Show str directly
    - Show list[str] directly
    - Show list[number] as collapsed numeric arrays
    - Ignore single numbers
    - Recurse into dict and list[dict]
    """
    rows = []

    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            rows.extend(_build_detail_rows(value, full_key))
        return rows

    if isinstance(data, list):
        if len(data) == 0:
            return rows

        if all(isinstance(item, str) and item.strip() for item in data):
            rows.append(
                {
                    "label": _format_detail_label(prefix),
                    "type": "string_list",
                    "value": data,
                }
            )
            return rows

        if _is_numeric_list(data):
            rows.append(
                {
                    "label": _format_detail_label(prefix),
                    "type": "numeric_array",
                    "count": len(data),
                    "json_value": json.dumps(data, indent=2, ensure_ascii=False),
                }
            )
            return rows

        for index, item in enumerate(data):
            item_prefix = f"{prefix}[{index}]"
            rows.extend(_build_detail_rows(item, item_prefix))
        return rows

    if isinstance(data, str) and data.strip():
        rows.append(
            {
                "label": _format_detail_label(prefix),
                "type": "string",
                "value": data,
            }
        )
        return rows

    return rows



PLOT_FIELD_PREFIXES = ("stress_", "strain_", "plastic_strain_")

def _extract_plot_variables(data, prefix=""):
    """
    Recursively extract plot-ready numeric arrays for mechanical variables
    """
    variables = []

    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, list) and _is_numeric_list(value) and key.startswith(PLOT_FIELD_PREFIXES):
                variables.append(
                    {
                        "key": full_key,
                        "label": _format_detail_label(full_key),
                        "short_label": key,
                        "values": value,
                    }
                )
            else:
                variables.extend(_extract_plot_variables(value, full_key))

    elif isinstance(data, list):
        for index, item in enumerate(data):
            item_prefix = f"{prefix}[{index}]"
            variables.extend(_extract_plot_variables(item, item_prefix))

    return variables




@login_required
def json_data_detail_view(request, pk):
    """
    Display a user-friendly detail page for one JSON data object
    """
    obj = get_object_or_404(JSONData, pk=pk, owner=request.user)

    detail_rows = _build_detail_rows(obj.data or {})
    string_rows = [row for row in detail_rows if row["type"] in {"string", "string_list"}]
    plot_variables = _extract_plot_variables(obj.data or {})

    context = {
        "data_object": obj,
        "detail_rows": string_rows,
        "plot_variables": plot_variables,
    }
    return render(request, "pages/data_detail.html", context)
