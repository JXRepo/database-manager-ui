import json

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, HttpResponse
from django.contrib.auth import login
from django.contrib.auth.models import User
from apps.pages.models import Product
from django.core import serializers
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import *
from .forms import SignUpForm, JSONUploadForm
from django.views.decorators.http import require_POST
from apps.dyn_api.helpers import validate_json
from numbers import Number

MAX_UPLOAD_FILES = 5


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
    Upload JSON files, validate data objects, and save valid objects to the database

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
            uploaded_files = form.cleaned_data["file"]

            if len(uploaded_files) > MAX_UPLOAD_FILES:
                messages.error(
                    request,
                    f"You can upload up to {MAX_UPLOAD_FILES} JSON files at once.",
                )
                return render(request, "pages/upload.html", {"form": form})

            total_created_count = 0
            processed_file_count = 0
            upload_errors = []

            for uploaded_file in uploaded_files:
                file_name = uploaded_file.name or "Uploaded file"

                try:
                    payload = json.load(uploaded_file)
                except json.JSONDecodeError:
                    upload_errors.append(f"{file_name}: Invalid JSON file.")
                    continue

                if isinstance(payload, list):
                    objects = payload
                elif isinstance(payload, dict):
                    if isinstance(payload.get("data"), list):
                        objects = payload["data"]
                    else:
                        objects = [payload]
                else:
                    upload_errors.append(
                        f"{file_name}: JSON must be a single object, a list of objects, or a dict with a 'data' list."
                    )
                    continue

                valid_objects, errors = validate_json(objects)

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

                processed_file_count += 1
                total_created_count += created_count

                for error in errors:
                    upload_errors.append(f"{file_name}: {error}")

                if created_count == 0 and errors:
                    upload_errors.append(f"{file_name}: No valid data objects were saved.")

            if total_created_count == 0 and upload_errors:
                messages.error(request, "Upload failed.")
                for error in upload_errors:
                    messages.error(request, error)

            elif total_created_count > 0 and upload_errors:
                messages.warning(
                    request,
                    (
                        "Upload partially successful: "
                        f"{total_created_count} object(s) saved from {processed_file_count} file(s)."
                    ),
                )
                for error in upload_errors:
                    messages.warning(request, error)

            elif total_created_count > 0:
                messages.success(
                    request,
                    (
                        "Upload successful: "
                        f"{total_created_count} object(s) saved from {processed_file_count} file(s)."
                    ),
                )

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


def _split_keyword_terms(keyword):
    """
    Split the basic search keyword into required terms
    """
    return [term for term in keyword.casefold().split() if term]


def _is_meaningful_search_string(value):
    """
    Return True when a string is useful for basic search
    """
    text = str(value).strip()

    if not text:
        return False

    if text.replace(".", "", 1).replace("-", "", 1).isdigit():
        return False

    return True


def _is_technical_search_key(key):
    """
    Return True for JSON keys that should not feed basic search
    """
    return str(key).strip().casefold() in {
        "$schema",
        "input_path",
        "results_path",
    }


def _is_identifier_search_key(key):
    """
    Return True for keys whose values are meaningful identifiers
    """
    normalized_key = str(key).strip().casefold()
    return normalized_key == "identifier" or normalized_key.endswith("_id")


def _collect_basic_search_values(value, key=""):
    """
    Collect meaningful text values from JSON while skipping numeric-only data
    """
    if _is_technical_search_key(key):
        return []

    if value is None or value == "":
        return []

    if isinstance(value, str):
        if _is_identifier_search_key(key):
            return [value.strip()] if value.strip() else []

        return [value.strip()] if _is_meaningful_search_string(value) else []

    if _is_number_value(value):
        if _is_identifier_search_key(key):
            return [str(value)]

        return []

    if isinstance(value, list):
        if value and all(_is_number_value(item) for item in value):
            return []

        values = []
        for item in value:
            values.extend(_collect_basic_search_values(item, key=key))
        return values

    if isinstance(value, dict):
        values = []
        for child_key, item in value.items():
            values.extend(_collect_basic_search_values(item, key=child_key))
        return values

    return [str(value)] if _is_meaningful_search_string(value) else []


def _build_basic_search_text(obj, access_text):
    """
    Build basic-search text from meaningful JSON values and ownership metadata
    """
    values = _collect_basic_search_values(obj.data or {})
    values.extend([obj.owner.username, access_text])
    return " ".join(str(value) for value in values if str(value).strip()).casefold()


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
    obj.list_display_name = data.get("identifier") or data.get("title") or "Object"
    obj.search_display_name = data.get("title") or data.get("identifier") or "Object"

    access_display = _get_access_display(obj)
    summary_fields.append(
        {
            "label": "Access",
            "value": access_display,
            "type": "access",
        }
    )

    obj.summary_fields = summary_fields
    return obj


def _build_data_object_filename(obj):
    """
    Build a compact JSON filename for one data object
    """
    data = obj.data or {}
    label = str(data.get("identifier") or data.get("title") or f"data_object_{obj.pk}")
    filename = []

    for character in label.strip():
        if character.isalnum() or character in {"-", "_"}:
            filename.append(character)
        else:
            filename.append("_")

    safe_name = "".join(filename).strip("_")[:80]

    if not safe_name:
        safe_name = f"data_object_{obj.pk}"

    return f"{safe_name}.json"


def _get_access_display(obj):
    """
    Return the access label shown in object summaries.

    Parameters
    ----------
    obj : JSONData
        Data object to inspect.

    Returns
    -------
    str
        Public, Shared, or Private.
    """
    if obj.access_type == "all":
        return "Public"

    if obj.shared_users.exists():
        return "Shared"

    return "Private"


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

    if obj.shared_users.filter(pk=user.pk).exists():
        return True

    return False


def _user_has_specific_share(obj, user):
    """
    Return True when access comes from a specific share.

    Parameters
    ----------
    obj : JSONData
        Data object to inspect.
    user : User
        Current user.

    Returns
    -------
    bool
        True when the user is not the owner and is explicitly shared.
    """
    if obj.owner_id == user.id:
        return False

    if obj.access_type == "all":
        return False

    if obj.shared_users.filter(pk=user.pk).exists():
        return True

    return False


def _find_share_user(identifier):
    """
    Find a user by username or email.

    Parameters
    ----------
    identifier : str
        Username or email address.

    Returns
    -------
    User or None
        Matching user, when one exists.
    """
    value = (identifier or "").strip()

    if not value:
        return None

    username_match = User.objects.filter(username__iexact=value).first()

    if username_match:
        return username_match

    return User.objects.filter(email__iexact=value).first()


@login_required
def json_data_list_view(request):
    """
    Display uploaded JSON data objects for the current user
    """
    data_objects = (
        JSONData.objects
        .filter(owner=request.user)
        .prefetch_related("shared_users")
        .order_by("-uploaded_at")
    )
    prepared_objects = [_prepare_list_object(obj) for obj in data_objects]

    context = {
        "segment": "data_list",
        "page_title": "My Data",
        "page_heading": "My Data",
        "breadcrumb_label": "My Data",
        "card_title": "My Uploaded Data Objects",
        "data_objects": prepared_objects,
        "empty_message": "No uploaded data found",
        "show_delete": True,
    }
    return render(request, "pages/data_list.html", context)


@login_required
def shared_with_me_view(request):
    """
    Display data objects explicitly shared with the current user
    """
    data_objects = (
        JSONData.objects
        .filter(shared_users=request.user)
        .exclude(owner=request.user)
        .select_related("owner")
        .prefetch_related("shared_users")
        .order_by("-uploaded_at")
    )
    prepared_objects = [_prepare_list_object(obj) for obj in data_objects]

    context = {
        "segment": "shared_with_me",
        "page_title": "Shared with Me",
        "page_heading": "Shared with Me",
        "breadcrumb_label": "Shared with Me",
        "card_title": "Data Objects Shared with Me",
        "data_objects": prepared_objects,
        "empty_message": "No data objects have been shared with you yet",
        "show_delete": False,
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

    if access not in {"public", "my_private"}:
        access = ""

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
        data_objects = (
            JSONData.objects
            .select_related("owner")
            .prefetch_related("shared_users")
            .order_by("-uploaded_at")
        )

        for obj in data_objects:
            if not _user_can_access_object(obj, request.user):
                continue

            data = obj.data or {}

            title_text = _normalize_search_value(data.get("title", ""))
            identifier_text = _normalize_search_value(data.get("identifier", ""))
            creator_text = _normalize_search_value(data.get("creator", ""))
            creator_affiliation_text = _normalize_search_value(
                data.get("creator_affiliation", "")
            )
            software_text = _normalize_search_value(data.get("software", ""))
            keywords_text = _normalize_search_value(data.get("keywords", ""))
            phase_text = _normalize_search_value(data.get("phase", ""))
            owner_text = _normalize_search_value(obj.owner.username)

            if _user_has_specific_share(obj, request.user):
                access_text = "shared with me"
            elif obj.owner_id == request.user.id and obj.access_type == "c":
                access_text = "my private"
            elif obj.access_type == "all":
                access_text = "public"
            else:
                access_text = "shared"

            full_text = _build_basic_search_text(obj, access_text)

            keyword_terms = _split_keyword_terms(keyword)

            if keyword_terms and not all(term in full_text for term in keyword_terms):
                continue

            if title and title.casefold() not in title_text.casefold():
                continue

            if identifier and identifier.casefold() not in identifier_text.casefold():
                continue

            creator_full_text = " ".join(
                [creator_text, creator_affiliation_text]
            ).casefold()

            if creator and creator.casefold() not in creator_full_text:
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


@login_required
@require_POST
def export_selected_search_results_view(request):
    """
    Export selected accessible data objects as a JSON file
    """
    selected_ids = request.POST.getlist("selected_objects")
    exported_objects = []

    for raw_id in selected_ids:
        try:
            object_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        try:
            obj = (
                JSONData.objects
                .select_related("owner")
                .prefetch_related("shared_users")
                .get(pk=object_id)
            )
        except JSONData.DoesNotExist:
            continue

        if not _user_can_access_object(obj, request.user):
            continue

        exported_objects.append(obj.data or {})

    if not exported_objects:
        messages.error(request, "Select at least one accessible data object to export.")
        return redirect("search")

    content = json.dumps(exported_objects, indent=2, ensure_ascii=False)
    response = HttpResponse(content, content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="selected_data_objects.json"'
    return response


@login_required
def json_data_export_view(request, pk):
    """
    Export one accessible JSON data object
    """
    obj = get_object_or_404(
        JSONData.objects.select_related("owner").prefetch_related("shared_users"),
        pk=pk,
    )

    if not _user_can_access_object(obj, request.user):
        raise Http404("Data object not found")

    content = json.dumps(obj.data or {}, indent=2, ensure_ascii=False)
    response = HttpResponse(content, content_type="application/json")
    response["Content-Disposition"] = (
        f'attachment; filename="{_build_data_object_filename(obj)}"'
    )
    return response



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

        if clean_part:
            parts.append(clean_part)

    return " / ".join(parts)






def _build_detail_rows(data, prefix=""):
    """
    Recursively build detail rows while preserving the original JSON order

    Rules
    -----
    - Show str directly
    - Show single numbers directly
    - Show list[str] directly
    - Show list[number] as collapsed numeric arrays
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

    if _is_number_value(data):
        rows.append(
            {
                "label": _format_detail_label(prefix),
                "type": "number",
                "value": data,
            }
        )
        return rows

    return rows


def _find_group_child(children, label):
    """Return an existing group child with the matching label

    Parameters
    ----------
    children : list
        Candidate child rows in the temporary group tree.
    label : str
        Group label to find.

    Returns
    -------
    dict or None
        The matching group row, or None when no match exists.
    """
    for child in children:
        if child.get("type") == "_group" and child.get("label") == label:
            return child
    return None


def _insert_auto_grouped_child(children, parts, row):
    """Insert one detail row into a nested group tree

    Parameters
    ----------
    children : list
        Mutable list of child rows at the current tree level.
    parts : list
        Ordered path parts for the row label.
    row : dict
        Detail row to insert.
    """
    if not parts:
        return

    if len(parts) == 1:
        leaf_row = row.copy()
        leaf_row["label"] = parts[0]
        children.append(leaf_row)
        return

    group_label = parts[0]
    group_node = _find_group_child(children, group_label)

    if group_node is None:
        group_node = {
            "type": "_group",
            "label": group_label,
            "children": [],
        }
        children.append(group_node)

    _insert_auto_grouped_child(group_node["children"], parts[1:], row)


def _count_group_leaves(node):
    """Count displayable leaf rows under a temporary group node

    Parameters
    ----------
    node : dict
        Temporary group node or detail row.

    Returns
    -------
    int
        Number of leaf rows below the node.
    """
    if node.get("type") != "_group":
        return 1

    return sum(_count_group_leaves(child) for child in node.get("children", []))


def _flatten_group_node(node, prefix=None):
    """Flatten a temporary group that does not need a collapsible section

    Parameters
    ----------
    node : dict
        Temporary group node to flatten.
    prefix : list, optional
        Parent labels already collected for the flattened label.

    Returns
    -------
    list
        Detail rows with restored slash-separated labels.
    """
    prefix = list(prefix or []) + [node.get("label", "")]
    rows = []

    for child in node.get("children", []):
        if child.get("type") == "_group":
            rows.extend(_flatten_group_node(child, prefix))
            continue

        leaf_row = child.copy()
        leaf_row["label"] = " / ".join(prefix + [str(child.get("label", ""))])
        rows.append(leaf_row)

    return rows


def _finalize_group_node(node):
    """Convert a temporary group tree into a template-ready group

    Parameters
    ----------
    node : dict
        Temporary group node.

    Returns
    -------
    dict
        Collapsible group row used by the templates.
    """
    children = []

    for child in node.get("children", []):
        if child.get("type") != "_group":
            children.append(child)
            continue

        if _count_group_leaves(child) >= 2:
            children.append(_finalize_group_node(child))
        else:
            children.extend(_flatten_group_node(child))

    return {
        "type": "group",
        "label": node.get("label", ""),
        "children": children,
        "count": _count_group_leaves(node),
    }


def _split_flat_group_label(label):
    """Split a flat metadata label into a group prefix and child label

    Parameters
    ----------
    label : str
        Flat field label to inspect.

    Returns
    -------
    tuple or None
        The prefix and child label when a supported split is found.
    """
    if not isinstance(label, str) or " / " in label:
        return None

    for separator in ("_", "-"):
        if separator in label:
            prefix, child = label.split(separator, 1)

            if prefix.strip() and child.strip():
                return prefix.strip(), child.strip()

    for index, character in enumerate(label[1:], start=1):
        if character.isupper():
            prefix = label[:index].strip()
            child = label[index:].strip()

            if prefix and child:
                return prefix, child

            break

    return None


def _group_repeated_flat_roots(rows):
    """Group top-level fields that share a repeated flat-name prefix

    Parameters
    ----------
    rows : list
        Detail rows after nested JSON path grouping.

    Returns
    -------
    list
        Rows with repeated flat prefixes converted into groups.
    """
    prefix_counts = {}

    for row in rows:
        label = str(row.get("label", ""))
        split_label = _split_flat_group_label(label)

        if split_label is None:
            continue

        prefix, _child = split_label

        if prefix:
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

    for row in rows:
        label = str(row.get("label", ""))

        if " / " in label:
            continue

        if label in prefix_counts:
            prefix_counts[label] += 1

    repeated_prefixes = {
        prefix
        for prefix, count in prefix_counts.items()
        if count >= 2
    }

    if not repeated_prefixes:
        return rows

    grouped_rows = []
    root_groups = {}

    for row in rows:
        label = str(row.get("label", ""))
        split_label = _split_flat_group_label(label)
        matched_prefix = None

        if label in repeated_prefixes:
            matched_prefix = label
            child_label = "value"
        elif split_label is not None and split_label[0] in repeated_prefixes:
            matched_prefix, child_label = split_label
        else:
            child_label = label

        if matched_prefix is None:
            grouped_rows.append(row)
            continue

        if matched_prefix not in root_groups:
            root_groups[matched_prefix] = {
                "type": "_group",
                "label": matched_prefix,
                "children": [],
            }
            grouped_rows.append(root_groups[matched_prefix])

        child_row = row.copy()
        child_row["label"] = child_label
        root_groups[matched_prefix]["children"].append(child_row)

    return grouped_rows


def _group_detail_rows(detail_rows):
    """Group hierarchical detail rows into nested collapsible sections

    Parameters
    ----------
    detail_rows : list
        Flat detail rows built from the JSON object.

    Returns
    -------
    list
        Detail rows and collapsible groups ready for rendering.
    """
    tree_rows = []

    for row in detail_rows:
        label = row.get("label", "")

        if isinstance(label, str) and " / " in label:
            _insert_auto_grouped_child(tree_rows, label.split(" / "), row)
            continue

        tree_rows.append(row)

    tree_rows = _group_repeated_flat_roots(tree_rows)

    grouped_rows = []

    for row in tree_rows:
        if row.get("type") != "_group":
            grouped_rows.append(row)
            continue

        if _count_group_leaves(row) >= 2:
            grouped_rows.append(_finalize_group_node(row))
        else:
            grouped_rows.extend(_flatten_group_node(row))

    return grouped_rows



PLOT_FIELD_PREFIXES = ("stress_", "strain_", "plastic_strain_")


def _get_plot_variable_unit(key, units):
    """
    Return the unit label for a plot variable
    """
    if not isinstance(units, dict):
        return ""

    if key.startswith("stress_"):
        unit = units.get("Stress", "")
    elif key.startswith(("strain_", "plastic_strain_")):
        unit = units.get("Strain", "")
    else:
        unit = ""

    if unit in ("", None):
        return ""

    if unit == 1 or str(unit).strip() == "1":
        return "-"

    return str(unit)


def _extract_plot_variables(data, prefix="", units=None):
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
                        "label": _format_plot_variable_label(full_key),
                        "short_label": key,
                        "unit": _get_plot_variable_unit(key, units),
                        "values": value,
                    }
                )
            else:
                variables.extend(_extract_plot_variables(value, full_key, units))

    elif isinstance(data, list):
        for index, item in enumerate(data):
            item_prefix = f"{prefix}[{index}]"
            variables.extend(_extract_plot_variables(item, item_prefix, units))

    return variables


def _format_plot_variable_label(path):
    """
    Format a plot variable label with the parent group and field name
    """
    parts = [part for part in _format_detail_label(path).split(" / ") if part]

    if len(parts) >= 2 and parts[-2] in {"total_strain", "plastic_strain", "stress"}:
        group_label = parts[-2].replace("_", " ").capitalize()
        return f"{group_label}: {parts[-1]}"

    return parts[-1] if parts else path




MECHANICAL_BC_DIRECTIONS = ("X", "Y", "Z")


def _format_mechanical_load_value(load):
    """
    Return a compact display value for one applied load
    """
    if not isinstance(load, dict):
        return ""

    magnitude = load.get("magnitude")
    if magnitude is None:
        return ""

    if _is_number_value(magnitude):
        return f"{magnitude:.4g}"

    return str(magnitude)


def _build_mechanical_bc_items(data):
    """
    Build normalized mechanical boundary condition items for the cube viewer
    """
    mechanical_bc = data.get("mechanical_BC", [])

    if not isinstance(mechanical_bc, list):
        return []

    items = []

    for condition in mechanical_bc:
        if not isinstance(condition, dict):
            continue

        vertices = condition.get("vertex_list", [])
        constraints = condition.get("constraints", [])
        applied_loads = condition.get("applied_load", [])

        if not isinstance(vertices, list):
            vertices = [vertices]

        if not isinstance(constraints, list):
            constraints = []

        if not isinstance(applied_loads, list):
            applied_loads = []

        load_index = 0
        axes = []

        for index, direction in enumerate(MECHANICAL_BC_DIRECTIONS):
            status = ""
            if index < len(constraints):
                status = str(constraints[index]).strip().casefold()

            load_label = ""
            raw_magnitude = None

            if status == "loaded":
                load = applied_loads[load_index] if load_index < len(applied_loads) else {}
                if isinstance(load, dict):
                    raw_magnitude = load.get("magnitude")
                load_label = _format_mechanical_load_value(load)
                load_index += 1

            axes.append(
                {
                    "direction": direction,
                    "status": status,
                    "load": load_label,
                    "magnitude": raw_magnitude,
                }
            )

        for vertex in vertices:
            vertex_name = str(vertex).strip()
            if not vertex_name:
                continue

            items.append(
                {
                    "vertex": vertex_name,
                    "axes": axes,
                    "loading_type": condition.get("loading_type", ""),
                    "loading_mode": condition.get("loading_mode", ""),
                }
            )

    return items






@login_required
@require_POST
def json_data_sharing_view(request, pk):
    """
    Update sharing settings for one data object.

    Parameters
    ----------
    request : HttpRequest
        Incoming POST request.
    pk : int
        Data object primary key.

    Returns
    -------
    HttpResponse
        Redirect to the detail page.
    """
    obj = get_object_or_404(JSONData, pk=pk, owner=request.user)
    action = request.POST.get("action", "").strip()

    if action == "add_user":
        identifier = request.POST.get("share_user", "")
        share_user = _find_share_user(identifier)

        if share_user is None:
            messages.error(request, "No user was found with that username or email.")
            return redirect("json_data_detail", pk=obj.pk)

        if share_user == request.user:
            messages.error(request, "You already own this data object.")
            return redirect("json_data_detail", pk=obj.pk)

        obj.shared_users.add(share_user)
        messages.success(request, f"Shared with {share_user.username}.")
        return redirect("json_data_detail", pk=obj.pk)

    if action == "remove_user":
        user_id = request.POST.get("user_id")
        share_user = get_object_or_404(User, pk=user_id)
        obj.shared_users.remove(share_user)
        messages.success(request, f"Removed sharing for {share_user.username}.")
        return redirect("json_data_detail", pk=obj.pk)

    messages.error(request, "Choose a valid sharing action.")
    return redirect("json_data_detail", pk=obj.pk)


@login_required
@require_POST
def json_data_delete_view(request, pk):
    """
    Delete one JSON data object owned by the current user
    """
    obj = get_object_or_404(JSONData, pk=pk, owner=request.user)
    obj.delete()
    messages.success(request, "Data object deleted successfully.")
    return redirect("json_data_list")






@login_required
def json_data_detail_view(request, pk):
    """
    Display a user-friendly detail page for one accessible JSON data object
    """
    obj = get_object_or_404(
        JSONData.objects.select_related("owner").prefetch_related("shared_users"),
        pk=pk,
    )

    if not _user_can_access_object(obj, request.user):
        raise Http404("Data object not found")

    detail_rows = _build_detail_rows(obj.data or {})
    display_rows = [
        row
        for row in detail_rows
        if row["type"] in {"string", "string_list", "number", "numeric_array"}
    ]
    display_rows = _group_detail_rows(display_rows)
    plot_variables = _extract_plot_variables(
        obj.data or {},
        units=(obj.data or {}).get("units", {}),
    )
    mechanical_bc_items = _build_mechanical_bc_items(obj.data or {})
    is_owner = obj.owner_id == request.user.id

    if is_owner:
        detail_back_url_name = "json_data_list"
        detail_back_label = "Back to My Data"
    elif _user_has_specific_share(obj, request.user):
        detail_back_url_name = "shared_with_me"
        detail_back_label = "Back to Shared with Me"
    else:
        detail_back_url_name = "search"
        detail_back_label = "Back to Search"

    context = {
        "data_object": obj,
        "detail_rows": display_rows,
        "plot_variables": plot_variables,
        "mechanical_bc_items": mechanical_bc_items,
        "shared_users": obj.shared_users.order_by("username"),
        "detail_back_url_name": detail_back_url_name,
        "detail_back_label": detail_back_label,
    }
    return render(request, "pages/data_detail.html", context)
