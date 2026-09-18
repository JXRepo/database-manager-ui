import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, HttpResponse, JsonResponse
from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.models import User
from apps.pages.models import Product
from django.core import serializers
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from .models import *
from .forms import AccountSettingsForm, ORCIDAccountSetupForm, SignUpForm, JSONUploadForm
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS, validate_json
from numbers import Number

from .rate_limits import consume_rate_limit, get_client_identifier
from .session_policy import apply_login_session_policy
from .advanced_search import (
    DATA_FIELD_CHOICES,
    DATA_FIELD_TYPES,
    MAX_CONDITIONS,
    OPERATOR_CHOICES,
    get_field_option,
    get_field_operators,
    matches_conditions,
    matches_whole_words,
    parse_conditions,
)
from .orcid_auth import (
    ORCID_TRANSACTION_SESSION_KEY,
    ORCIDFlowError,
    _sanitize_next_url,
    complete_orcid_link,
    complete_orcid_login,
    consume_orcid_transaction,
    normalize_orcid,
    start_orcid_transaction,
)
from .notifications import build_shared_data_notification_message
from .upload_services import (
    UploadIdentifierConflict,
    PreparedJSONData,
    UploadResourceLimitError,
    canonical_json_size,
    data_fingerprint,
    generate_data_identifier,
    save_prepared_json_data,
    validate_json_depth,
    validate_upload_files,
)

SHORT_NUMERIC_ARRAY_INLINE_LIMIT = 6
ASSISTANT_MAX_QUESTION_LENGTH = 600
SHARE_USERNAME_KEY = "username"
UPLOAD_ISSUE_CATEGORIES = (
    ("invalid_file", "Invalid files"),
    ("invalid_structure", "Invalid JSON structure"),
    ("missing_required", "Missing required fields"),
    ("empty_values", "Empty values"),
    ("duplicate_identifier", "Duplicate identifiers"),
    ("invalid_access", "Invalid access metadata"),
    ("unknown_share_user", "Unknown shared users"),
    ("self_share", "Invalid share targets"),
    ("other_validation", "Other validation issues"),
)
MECHANICAL_BC_VERTICES = (
    "V000",
    "V100",
    "V010",
    "V110",
    "V001",
    "V101",
    "V011",
    "V111",
)
ORCID_AUTH_SCOPE = "/authenticate"


def index(request):
    """Show the public landing page or redirect signed-in users to search"""
    if request.user.is_authenticated:
        return redirect("search")

    return render(request, "pages/index.html")


def healthz_view(request):
    """Return application readiness based on a live database query"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)

    return JsonResponse({"status": "ok"})

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
  """
  Register a new user and start an ordinary fixed login session

  Registration uses the thirty day default without remembered session renewal.

  Parameters
  ----------
  request : HttpRequest
      Request to display or submit the registration form.

  Returns
  -------
  HttpResponse
      Registration form, rate limit response, or redirect after login.
  """
  if request.method == "POST":
    try:
      decision = consume_rate_limit(
        "registration",
        get_client_identifier(request),
      )
    except DatabaseError:
      return HttpResponse("Service unavailable.", status=503)

    if not decision.allowed:
      response = HttpResponse("Too many requests.", status=429)
      response["Retry-After"] = str(decision.retry_after_seconds)
      return response

    form = SignUpForm(request.POST)
    if form.is_valid():
      user = form.save()
      login(request, user)
      apply_login_session_policy(request)
      return redirect("search")
  else:
    form = SignUpForm()

  return render(request, "accounts/register.html", {"form": form})


@login_required
def account_settings_view(request):
    """
    Update the signed-in user's basic account settings
    """
    profile, _created = AccountProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = AccountSettingsForm(request.POST, instance=request.user)

        if form.is_valid():
            form.save()
            profile.institution = form.cleaned_data["institution"]
            profile.save(update_fields=["institution"])
            messages.success(request, "Account settings updated.")
            return redirect("account_settings")
    else:
        form = AccountSettingsForm(instance=request.user)

    return render(
        request,
        "accounts/settings.html",
        {"form": form, "profile": profile},
    )


@login_required
@require_POST
def orcid_disconnect_view(request):
    """
    Disconnect the current account only when a local password remains available

    Serialize identity changes with OAuth callbacks and reject stale forms.
    Existing account data and legacy profile text are not removed.

    Parameters
    ----------
    request : HttpRequest
        Authenticated POST containing the displayed verified ORCID iD.

    Returns
    -------
    HttpResponse
        Settings redirect with the result or an inactive account refusal.
    """
    with transaction.atomic():
        current_user = User.objects.select_for_update().filter(pk=request.user.pk).first()
        if current_user is None or not current_user.is_active:
            return HttpResponse("Account unavailable.", status=403)
        profile = (
            AccountProfile.objects.select_for_update().filter(user=current_user).first()
        )
        if profile is None or not profile.authenticated_orcid:
            messages.info(request, "ORCID is already disconnected.")
            return redirect("account_settings")
        if request.POST.get("orcid") != profile.authenticated_orcid:
            messages.error(request, "Your ORCID connection changed. Please try again.")
            return redirect("account_settings")
        if not current_user.has_usable_password():
            return redirect("orcid_setup_credentials")

        profile.authenticated_orcid = None
        profile.orcid_authenticated_at = None
        profile.orcid_disconnected_at = timezone.now()
        profile.save(
            update_fields=[
                "authenticated_orcid",
                "orcid_authenticated_at",
                "orcid_disconnected_at",
            ]
        )

    request.session.pop(ORCID_TRANSACTION_SESSION_KEY, None)
    messages.success(
        request,
        "ORCID disconnected. You can still sign in with your username and password.",
    )
    return redirect("account_settings")


@login_required
@require_http_methods(["GET", "POST"])
def orcid_setup_credentials_view(request):
    """
    Require a chosen username and password before using an ORCID account

    Update the same account under a lock and retain its current login session.
    Completing setup never disconnects the verified identity.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request to display or submit the required setup modal.

    Returns
    -------
    HttpResponse
        Setup modal with errors or a safe local redirect after completion.
    """
    next_url = _sanitize_next_url(
        request,
        request.POST.get("next") if request.method == "POST" else request.GET.get("next"),
    )
    if not next_url.startswith(("/", "http://", "https://")):
        next_url = reverse("search")
    with transaction.atomic():
        current_user = User.objects.select_for_update().filter(pk=request.user.pk).first()
        if current_user is None or not current_user.is_active:
            return HttpResponse("Account unavailable.", status=403)
        if current_user.has_usable_password():
            return redirect("search")
        profile = (
            AccountProfile.objects.select_for_update().filter(user=current_user).first()
        )
        if profile is None or not profile.authenticated_orcid:
            return HttpResponse("Account setup is unavailable.", status=403)
        if request.method == "POST" and request.POST.get("orcid") != profile.authenticated_orcid:
            messages.error(request, "Your ORCID connection changed. Please try again.")
            return redirect("orcid_setup_credentials")

        setup_form = ORCIDAccountSetupForm(
            request.POST if request.method == "POST" else None,
            instance=current_user,
            prefix="orcid_setup",
            initial={"username": ""},
        )
        if request.method == "POST" and setup_form.is_valid():
            try:
                with transaction.atomic():
                    updated_user = setup_form.save()
            except IntegrityError:
                setup_form.add_error("username", "A user with that username already exists.")
            else:
                update_session_auth_hash(request, updated_user)
                request.session.pop("orcid_disconnect_confirmation", None)
                request.session.pop("orcid_setup_requested", None)
                messages.success(request, "Username and password set successfully.")
                return redirect(next_url)

    return render(
        request,
        "accounts/orcid_setup.html",
        {
            "profile": profile,
            "orcid_setup_form": setup_form,
            "next_url": next_url,
        },
    )


def _get_orcid_base_url():
    """
    Return the configured ORCID base URL without a trailing slash
    """
    return getattr(settings, "ORCID_BASE_URL", "https://sandbox.orcid.org").rstrip("/")


def _get_orcid_redirect_uri(request):
    """
    Return the redirect URI registered with ORCID
    """
    configured_uri = getattr(settings, "ORCID_REDIRECT_URI", "").strip()

    if configured_uri:
        return configured_uri

    return request.build_absolute_uri(reverse("orcid_callback"))


def _build_orcid_authorization_url(request, state, client_id):
    """
    Build the ORCID authorization URL for login or account linking
    """
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": ORCID_AUTH_SCOPE,
            "redirect_uri": _get_orcid_redirect_uri(request),
            "state": state,
        }
    )
    return f"{_get_orcid_base_url()}/oauth/authorize?{query}"


def _exchange_orcid_authorization_code(code, redirect_uri):
    """
    Exchange an ORCID authorization code for token response data
    """
    body = urlencode(
        {
            "client_id": settings.ORCID_CLIENT_ID,
            "client_secret": settings.ORCID_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    request = Request(
        f"{_get_orcid_base_url()}/oauth/token",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _start_orcid_authorization(request, intent, user_id, failure_url, message):
    """
    Start one rate limited ORCID authorization transaction

    Store the browser's login preference without changing an existing session.

    Parameters
    ----------
    request : HttpRequest
        Request carrying a local redirect and optional persistence choice.
    intent : str
        Login or link action to authorize.
    user_id : int or None
        Account initiating a link action.
    failure_url : str
        Local destination when provider setup is unavailable.
    message : str
        User facing explanation when provider setup is unavailable.

    Returns
    -------
    HttpResponse
        Provider authorization redirect or a controlled failure response.
    """
    had_transaction = ORCID_TRANSACTION_SESSION_KEY in request.session
    request.session.pop(ORCID_TRANSACTION_SESSION_KEY, None)
    if had_transaction:
        request.session.save()

    client_id = getattr(settings, "ORCID_CLIENT_ID", "")
    client_secret = getattr(settings, "ORCID_CLIENT_SECRET", "")

    if not isinstance(client_id, str) or not client_id.strip():
        messages.error(request, message)
        return redirect(failure_url)
    if not isinstance(client_secret, str) or not client_secret.strip():
        messages.error(request, message)
        return redirect(failure_url)

    try:
        decision = consume_rate_limit(
            "orcid_start",
            get_client_identifier(request),
        )
    except DatabaseError:
        return HttpResponse("Service unavailable.", status=503)

    if not decision.allowed:
        response = HttpResponse("Too many requests.", status=429)
        response["Retry-After"] = str(max(1, decision.retry_after_seconds))
        return response

    state = start_orcid_transaction(
        request,
        intent,
        user_id=user_id,
        next_url=request.GET.get("next", ""),
        remember_me=intent == "login" and request.GET.get("remember_me") == "on",
    )
    return redirect(
        _build_orcid_authorization_url(
            request,
            state,
            client_id.strip(),
        )
    )


@require_GET
def orcid_login_view(request):
    """
    Redirect an anonymous user to ORCID sign in
    """
    return _start_orcid_authorization(
        request,
        intent="login",
        user_id=None,
        failure_url=settings.LOGIN_URL,
        message="ORCID sign in is not configured yet.",
    )


@login_required
@require_GET
def orcid_connect_view(request):
    """
    Redirect the signed in user to ORCID account linking
    """
    return _start_orcid_authorization(
        request,
        intent="link",
        user_id=request.user.pk,
        failure_url="account_settings",
        message="ORCID connection is not configured yet.",
    )


@require_GET
def orcid_callback_view(request):
    """
    Complete one consumed ORCID login or route a valid link safely

    Parameters
    ----------
    request : HttpRequest
        Provider callback request carrying state and authorization results.

    Returns
    -------
    HttpResponse
        Login result or a fixed local error redirect.
    """
    try:
        orcid_transaction = consume_orcid_transaction(
            request,
            request.GET.get("state"),
        )
    except ORCIDFlowError:
        messages.error(request, "ORCID sign in could not be verified.")
        return redirect(settings.LOGIN_URL)

    failure_url = (
        "account_settings"
        if orcid_transaction.intent == "link"
        else settings.LOGIN_URL
    )

    if "error" in request.GET:
        messages.error(request, "ORCID authorization was cancelled.")
        return redirect(failure_url)

    code = request.GET.get("code")
    if not isinstance(code, str) or not code.strip():
        messages.error(request, "ORCID did not return an authorization code.")
        return redirect(failure_url)

    try:
        token_data = _exchange_orcid_authorization_code(
            code,
            _get_orcid_redirect_uri(request),
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        messages.error(request, "ORCID sign in failed. Please try again.")
        return redirect(failure_url)

    if type(token_data) is not dict:
        messages.error(request, "ORCID sign in failed. Please try again.")
        return redirect(failure_url)

    access_token = token_data.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        messages.error(request, "ORCID sign in failed. Please try again.")
        return redirect(failure_url)

    try:
        orcid = normalize_orcid(token_data.get("orcid"))
    except ORCIDFlowError:
        messages.error(request, "ORCID sign in failed. Please try again.")
        return redirect(failure_url)

    if orcid_transaction.intent == "link":
        return complete_orcid_link(
            request,
            orcid_transaction,
            orcid,
        )

    return complete_orcid_login(
        request,
        orcid,
        orcid_transaction.next_url,
        remember_me=orcid_transaction.remember_me,
    )


def _get_shared_with_entries(data):
    """
    Return normalized sharing entries from one JSON object

    Parameters
    ----------
    data : dict
        Parsed JSON data object.

    Returns
    -------
    list
        Sharing entries from the top-level shared_with field.
    """
    shared_with = data.get("shared_with", [])

    if isinstance(shared_with, list):
        return shared_with

    if isinstance(shared_with, dict):
        return [shared_with]

    return []


def _get_upload_access_type(data):
    """
    Return the stored access type for an uploaded JSON object

    Parameters
    ----------
    data : dict
        Parsed JSON data object.

    Returns
    -------
    str
        The stored access type, either all or c.
    """
    for item in _get_shared_with_entries(data):
        if not isinstance(item, dict):
            continue

        access_type = str(item.get("access_type", "c")).strip().casefold()

        if access_type == "all":
            return "all"

    return "c"


def _get_share_username(item):
    """
    Return the username value from one sharing entry

    Parameters
    ----------
    item : dict
        One shared_with entry from the uploaded JSON metadata.

    Returns
    -------
    str
        The stripped username value.
    """
    if not isinstance(item, dict):
        return ""

    return str(item.get(SHARE_USERNAME_KEY, "")).strip()


def _add_upload_issue(upload_issues, category, message):
    """
    Add one upload issue to its display category

    Parameters
    ----------
    upload_issues : dict
        Mapping of issue category keys to message lists.
    category : str
        Issue category key.
    message : str
        User-facing issue detail.
    """
    upload_issues.setdefault(category, []).append(message)


def _get_upload_issue_messages(upload_issues):
    """
    Build numbered upload issue messages grouped by category

    Parameters
    ----------
    upload_issues : dict
        Mapping of issue category keys to message lists.

    Returns
    -------
    list
        Numbered messages for display through Django messages.
    """
    numbered_messages = []
    issue_number = 1

    for category, label in UPLOAD_ISSUE_CATEGORIES:
        details = upload_issues.get(category, [])

        if not details:
            continue

        numbered_messages.append(
            f"{issue_number}. {label}: {'; '.join(details)}"
        )
        issue_number += 1

    return numbered_messages


def _categorize_validation_error(error):
    """
    Return the upload issue category for one schema validation message

    Parameters
    ----------
    error : str
        Validation error returned by validate_json.

    Returns
    -------
    str
        Upload issue category key.
    """
    error_text = error.casefold()

    if "missing required" in error_text:
        return "missing_required"

    if "empty " in error_text:
        return "empty_values"

    return "other_validation"


def _resolve_upload_access_metadata(data, owner):
    """
    Resolve upload access type and username sharing metadata

    Parameters
    ----------
    data : dict
        Parsed JSON data object.
    owner : User
        User uploading the data object.

    Returns
    -------
    tuple
        Stored access type, resolved shared users, and issue dictionaries.
    """
    users = []
    issues = []
    seen_user_ids = set()
    access_type = _get_upload_access_type(data)

    for index, item in enumerate(_get_shared_with_entries(data), start=1):
        if not isinstance(item, dict):
            issues.append(
                (
                    "invalid_access",
                    f"shared_with entry {index} must be an object.",
                )
            )
            continue

        has_access_type_key = "access_type" in item
        raw_access_type = item.get("access_type", "c")
        item_access_type = str(raw_access_type).strip().casefold()

        if has_access_type_key and not item_access_type:
            issues.append(
                (
                    "empty_values",
                    f"shared_with entry {index} has an empty access_type.",
                )
            )
            continue

        if item_access_type not in {"all", "c"}:
            issues.append(
                (
                    "invalid_access",
                    (
                        f'shared_with entry {index} has invalid access_type '
                        f'"{raw_access_type}". Use "all" for public data or '
                        f'"c" for private or shared data.'
                    ),
                )
            )
            continue

        has_username_key = SHARE_USERNAME_KEY in item
        username = _get_share_username(item)

        if access_type == "all":
            if has_username_key:
                issues.append(
                    (
                        "invalid_access",
                        (
                            f'shared_with entry {index} cannot include username '
                            'when access_type is "all". Public data is already '
                            "available through Search."
                        ),
                    )
                )
            continue

        if item_access_type == "all":
            continue

        if not has_username_key:
            continue

        if not username:
            issues.append(
                (
                    "empty_values",
                    f"shared_with entry {index} has an empty username.",
                )
            )
            continue

        share_user = _find_share_user(username)

        if share_user is None:
            issues.append(
                (
                    "unknown_share_user",
                    (
                        f'username "{username}" in shared_with entry {index} '
                        "does not exist."
                    ),
                )
            )
            continue

        if share_user.pk == owner.pk:
            issues.append(
                (
                    "self_share",
                    (
                        f'username "{username}" is the owner. Remove username '
                        "to keep this object private."
                    ),
                )
            )
            continue

        if share_user.pk in seen_user_ids:
            continue

        users.append(share_user)
        seen_user_ids.add(share_user.pk)

    return access_type, users, issues


def _identifier_exists(identifier):
    """
    Return True when an identifier already exists in stored JSON data

    Parameters
    ----------
    identifier : str
        Top-level JSON identifier to check.

    Returns
    -------
    bool
        True when any JSONData row already stores this identifier.
    """
    return JSONData.objects.filter(data__identifier=identifier).exists()


def _get_data_object_display_title(data_object):
    """
    Return the best display title for one data object
    """
    data = data_object.data or {}
    return data.get("identifier") or data.get("title") or "Data object"


def _create_shared_data_notification(data_object, actor, recipient):
    """
    Create a notification for one private data share
    """
    if actor.pk == recipient.pk:
        return None

    if data_object.access_type != "c":
        return None

    title = _get_data_object_display_title(data_object)

    return DataNotification.objects.create(
        recipient=recipient,
        actor=actor,
        data_object=data_object,
        notification_type=DataNotification.TYPE_SHARED_DATA,
        message=build_shared_data_notification_message(actor, title),
    )


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
        try:
            decision = consume_rate_limit("upload", str(request.user.pk))
        except DatabaseError:
            return HttpResponse("Service unavailable.", status=503)

        if not decision.allowed:
            response = HttpResponse("Too many requests.", status=429)
            response["Retry-After"] = str(decision.retry_after_seconds)
            return response

        form = JSONUploadForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_files = form.cleaned_data["file"]
            processed_file_count = 0
            upload_issues = {}
            seen_identifiers = set()
            prepared_object_labels = {}
            prepared_objects = []
            raw_object_count = 0

            try:
                validate_upload_files(uploaded_files)

                for uploaded_file in uploaded_files:
                    file_name = uploaded_file.name or "Uploaded file"

                    try:
                        payload = json.load(uploaded_file)
                    except RecursionError as error:
                        raise UploadResourceLimitError(
                            "Uploaded JSON exceeds the maximum container depth."
                        ) from error
                    except ValueError:
                        _add_upload_issue(
                            upload_issues,
                            "invalid_file",
                            f"{file_name} is not valid JSON.",
                        )
                        continue

                    validate_json_depth(payload)

                    if isinstance(payload, list):
                        objects = payload
                    elif isinstance(payload, dict):
                        if isinstance(payload.get("data"), list):
                            objects = payload["data"]
                        else:
                            objects = [payload]
                    else:
                        _add_upload_issue(
                            upload_issues,
                            "invalid_structure",
                            (
                                f"{file_name} must be a single object, a list of objects, "
                                "or a dict with a 'data' list."
                            ),
                        )
                        continue

                    raw_object_count += len(objects)

                    if raw_object_count > settings.PILOT_MAX_UPLOAD_OBJECTS:
                        raise UploadResourceLimitError(
                            "The upload exceeds the maximum number of JSON data objects."
                        )

                    valid_objects, errors = validate_json(objects)
                    object_indexes = {}

                    for object_index, obj in enumerate(objects, start=1):
                        if isinstance(obj, dict):
                            object_indexes[id(obj)] = object_index

                    prepared_count = 0

                    for obj in valid_objects:
                        object_index = object_indexes.get(id(obj), 1)
                        identifier = obj.get("identifier")
                        fingerprint = ""
                        if identifier is None or not identifier.strip():
                            fingerprint = data_fingerprint(obj)
                            identifier = generate_data_identifier(obj, prepared_objects)
                            obj["identifier"] = identifier
                        object_label = f"{file_name} data object {object_index}"

                        if identifier in seen_identifiers:
                            _add_upload_issue(
                                upload_issues,
                                "duplicate_identifier",
                                (
                                    f'{object_label}: identifier "{identifier}" is duplicated '
                                    "in this upload. Please remove the duplicate, or provide "
                                    "a different identifier if this is a distinct data object."
                                ),
                            )
                            continue

                        if _identifier_exists(identifier):
                            _add_upload_issue(
                                upload_issues,
                                "duplicate_identifier",
                                (
                                    f'{object_label}: identifier "{identifier}" already exists. '
                                    "Please remove the duplicate, or provide a different "
                                    "identifier if this is a distinct data object."
                                ),
                            )
                            continue

                        access_type, shared_users, access_issues = (
                            _resolve_upload_access_metadata(
                                obj,
                                request.user,
                            )
                        )

                        if access_issues:
                            for category, issue in access_issues:
                                _add_upload_issue(
                                    upload_issues,
                                    category,
                                    f"{object_label}: {issue}",
                                )
                            continue

                        prepared_objects.append(
                            PreparedJSONData(
                                data=obj,
                                access_type=access_type,
                                shared_users=tuple(shared_users),
                                size_bytes=canonical_json_size(obj),
                                identifier_fingerprint=fingerprint,
                            )
                        )
                        prepared_object_labels[identifier] = object_label
                        seen_identifiers.add(identifier)
                        if fingerprint:
                            seen_identifiers.add(fingerprint)
                        prepared_count += 1

                    processed_file_count += 1

                    for error in errors:
                        category = _categorize_validation_error(error)
                        _add_upload_issue(
                            upload_issues,
                            category,
                            f"{file_name}: {error}",
                        )

                    if prepared_count == 0 and errors:
                        _add_upload_issue(
                            upload_issues,
                            "other_validation",
                            f"{file_name}: No valid data objects were saved.",
                        )

                saved_objects = save_prepared_json_data(
                    request.user,
                    prepared_objects,
                )
            except UploadIdentifierConflict as error:
                for identifier in error.identifiers:
                    object_label = prepared_object_labels.get(
                        identifier,
                        "Uploaded data object",
                    )
                    _add_upload_issue(
                        upload_issues,
                        "duplicate_identifier",
                        (
                            f'{object_label}: identifier "{identifier}" or its generated '
                            "content already exists. "
                            "Please remove the duplicate, or provide a different "
                            "identifier if this is a distinct data object."
                        ),
                    )

                messages.error(request, "Upload failed.")
                for issue in _get_upload_issue_messages(upload_issues):
                    messages.error(request, issue)
                return render(request, "pages/upload.html", {"form": form})
            except UploadResourceLimitError as error:
                messages.error(request, "Upload failed.")
                messages.error(request, str(error))
                return render(request, "pages/upload.html", {"form": form})

            total_created_count = len(saved_objects)

            upload_issue_messages = _get_upload_issue_messages(upload_issues)

            if total_created_count == 0 and upload_issue_messages:
                messages.error(request, "Upload failed.")
                for issue in upload_issue_messages:
                    messages.error(request, issue)

            elif total_created_count > 0 and upload_issue_messages:
                messages.warning(
                    request,
                    (
                        "Upload partially successful: "
                        f"{total_created_count} object(s) saved from {processed_file_count} file(s)."
                    ),
                )
                for issue in upload_issue_messages:
                    messages.warning(request, issue)

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


def _assistant_text(value):
    """
    Return compact text for assistant answers

    Parameters
    ----------
    value : object
        Value from JSON metadata.

    Returns
    -------
    str
        Human-readable text.
    """
    text = _format_summary_value(value)
    return "" if text == "-" else text


def _assistant_phase_names(data):
    """
    Return phase names from one JSON data object

    Parameters
    ----------
    data : dict
        Parsed JSON data object.

    Returns
    -------
    list
        Phase labels found in the data.
    """
    phases = data.get("phase", [])
    names = []

    if isinstance(phases, list):
        for phase in phases:
            if isinstance(phase, dict):
                name = (
                    phase.get("phase_identifier")
                    or phase.get("name")
                    or phase.get("identifier")
                )
                if name:
                    names.append(str(name))
            elif phase:
                names.append(str(phase))
    elif phases:
        names.append(str(phases))

    return names


def _assistant_access_summary(obj):
    """
    Return the assistant access summary for one object

    Parameters
    ----------
    obj : JSONData
        Data object to inspect.

    Returns
    -------
    str
        Access summary.
    """
    if obj.access_type == "all":
        return "Access: Public. Other users can find this object through Search."

    shared_count = obj.shared_users.count()

    if shared_count:
        return (
            "Access: Private and shared. The owner can always view it, and "
            f"{shared_count} explicitly shared user(s) can also view it."
        )

    return "Access: Private. Only the owner can view it."


def _assistant_mechanical_bc_summary(data):
    """
    Return a compact mechanical boundary condition summary

    Parameters
    ----------
    data : dict
        Parsed JSON data object.

    Returns
    -------
    str
        Boundary condition summary.
    """
    items = _build_mechanical_bc_items(data)

    if not items:
        return "I did not find usable mechanical_BC data in this object."

    defined_items = [item for item in items if item.get("is_defined") is not False]
    loaded = []
    fixed = []

    for item in defined_items:
        vertex = item.get("vertex", "")

        for axis in item.get("axes", []):
            direction = axis.get("direction", "")
            status = axis.get("status", "")

            if status == "loaded":
                label = f"{vertex} {direction}"
                if axis.get("load"):
                    label = f"{label} ({axis['load']})"
                loaded.append(label)
            elif status == "fixed":
                fixed.append(f"{vertex} {direction}")

    lines = [
        f"Mechanical boundary conditions are defined on {len(defined_items)} vertex/vertices."
    ]

    if fixed:
        lines.append(f"Fixed constraints: {', '.join(fixed)}.")

    if loaded:
        lines.append(f"Loaded directions: {', '.join(loaded)}.")

    return "\n".join(lines)


def _assistant_plot_summary(data):
    """
    Return a summary of plot-ready variables

    Parameters
    ----------
    data : dict
        Parsed JSON data object.

    Returns
    -------
    str
        Plot guidance.
    """
    variables = _extract_plot_variables(data, units=data.get("units", {}))

    if not variables:
        return "I did not find plot-ready numeric arrays in this object."

    stress_variables = [
        variable for variable in variables
        if "stress" in variable.get("key", "").casefold()
    ]
    strain_variables = [
        variable for variable in variables
        if "strain" in variable.get("key", "").casefold()
    ]

    lines = [f"I found {len(variables)} plot-ready numeric variable(s)."]

    if stress_variables and strain_variables:
        lines.append(
            "A natural first plot is a stress component against the matching "
            "strain component, for example stress_11 vs strain_11 if both are present."
        )
    else:
        examples = [variable.get("short_label", "") for variable in variables[:4]]
        examples = [example for example in examples if example]

        if examples:
            lines.append(f"Examples: {', '.join(examples)}.")

    return "\n".join(lines)


def _assistant_object_overview(obj):
    """
    Return a compact overview for one accessible data object

    Parameters
    ----------
    obj : JSONData
        Data object to summarize.

    Returns
    -------
    str
        Object summary.
    """
    data = obj.data or {}
    title = _assistant_text(data.get("title")) or "Untitled data object"
    identifier = _assistant_text(data.get("identifier")) or "No identifier"
    software = _assistant_text(data.get("software")) or "Software not specified"
    phases = _assistant_phase_names(data)

    lines = [
        f"{title}",
        f"Identifier: {identifier}",
        f"Software: {software}",
    ]

    if phases:
        lines.append(f"Phase: {', '.join(phases)}")

    lines.append(_assistant_access_summary(obj))
    return "\n".join(lines)


def _assistant_upload_answer(question):
    """
    Return assistant guidance for the upload workflow

    Parameters
    ----------
    question : str
        User question.

    Returns
    -------
    str
        Upload guidance.
    """
    normalized_question = question.casefold()

    if "share" in normalized_question or "username" in normalized_question:
        return (
            'For sharing, use shared_with with access_type "c" and a username.\n'
            'If access_type is "c" and username is absent, the object stays private.\n'
            'If username is present, it must match an existing system username.\n'
            'Use access_type "all" for public data; public data should not include username.'
        )

    if "identifier" in normalized_question or "duplicate" in normalized_question:
        return (
            "Each uploaded data object must have a unique identifier. If the same "
            "identifier already exists in the database or appears twice in one upload, "
            "that object is rejected and the upload message lists the duplicate."
        )

    if (
        "empty" in normalized_question
        or "missing" in normalized_question
        or "required" in normalized_question
    ):
        return (
            "Upload validation checks required top-level fields and empty top-level values. "
            "Errors are grouped by category, such as missing required fields, empty values, "
            "duplicate identifiers, invalid access metadata, and unknown shared users."
        )

    return (
        "Upload accepts JSON files with one object, a list of objects, or a dict containing "
        "a data list. Valid objects are saved; objects with missing fields, empty values, "
        "invalid sharing metadata, unknown usernames, or duplicate identifiers are rejected."
    )


def _assistant_search_answer(question):
    """
    Return assistant guidance for the search workflow

    Parameters
    ----------
    question : str
        User question.

    Returns
    -------
    str
        Search guidance.
    """
    normalized_question = question.casefold()
    suggestions = []

    if "public" in normalized_question:
        suggestions.append("set Access to Public")

    if "private" in normalized_question:
        suggestions.append("set Access to My Private")

    for term in ("copper", "goss", "abaqus", "stress", "strain"):
        if term in normalized_question:
            suggestions.append(f'use "{term}" as a keyword or field filter')

    if "phase" in normalized_question:
        suggestions.append("use the Phase field")

    if "software" in normalized_question:
        suggestions.append("use the Software field")

    if suggestions:
        return "Suggested search setup: " + "; ".join(suggestions) + "."

    return (
        "Use the main search box for broad keywords. Use Advanced Search when you know "
        "a specific identifier, creator, software, phase, owner, or access type."
    )


def _assistant_detail_answer(question, obj):
    """
    Return assistant guidance for one detail page object

    Parameters
    ----------
    question : str
        User question.
    obj : JSONData
        Accessible data object.

    Returns
    -------
    str
        Detail page answer.
    """
    normalized_question = question.casefold()
    data = obj.data or {}

    if any(
        term in normalized_question
        for term in ("boundary", "mechanical", "bc", "vertex", "fixed", "loaded")
    ):
        return _assistant_mechanical_bc_summary(data)

    if any(term in normalized_question for term in ("plot", "curve", "stress", "strain", "variable")):
        return _assistant_plot_summary(data)

    if any(term in normalized_question for term in ("access", "share", "private", "public")):
        return _assistant_access_summary(obj)

    if any(term in normalized_question for term in ("phase", "material")):
        phases = _assistant_phase_names(data)

        if phases:
            return "Phase information: " + ", ".join(phases) + "."

        return "I did not find phase information in this object."

    if "software" in normalized_question:
        software = _assistant_text(data.get("software"))
        version = _assistant_text(data.get("software_version"))

        if software and version:
            return f"Software: {software} {version}."

        if software:
            return f"Software: {software}."

        return "I did not find software information in this object."

    return _assistant_object_overview(obj)


def _build_assistant_answer(question, page, obj=None):
    """
    Build a read-only assistant answer for the current page

    Parameters
    ----------
    question : str
        User question.
    page : str
        Current assistant page context.
    obj : JSONData, optional
        Accessible data object for detail answers.

    Returns
    -------
    tuple
        Answer text and suggested follow-up prompts.
    """
    if obj is not None:
        suggestions = [
            "Summarize this data",
            "Explain mechanical_BC",
            "What can I plot?",
            "How is access set?",
        ]
        return _assistant_detail_answer(question, obj), suggestions

    if page == "upload":
        suggestions = [
            "How should I write shared_with?",
            "What if identifier already exists?",
            "Why did upload reject empty values?",
        ]
        return _assistant_upload_answer(question), suggestions

    suggestions = [
        "How do I find copper data?",
        "How do I search by phase?",
        "How do I find public data?",
    ]
    return _assistant_search_answer(question), suggestions


@login_required
@require_POST
def fair_assistant_ask_view(request):
    """
    Answer a read-only FAIR data assistant question

    Parameters
    ----------
    request : HttpRequest
        AJAX request containing question, page, and optional object_id.

    Returns
    -------
    JsonResponse
        Assistant answer and suggested follow-up prompts.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid assistant request."}, status=400)

    question = str(payload.get("question", "")).strip()
    page = str(payload.get("page", "search")).strip().casefold()
    object_id = payload.get("object_id")

    if not question:
        return JsonResponse({"error": "Enter a question for the assistant."}, status=400)

    question = question[:ASSISTANT_MAX_QUESTION_LENGTH]
    obj = None

    if object_id:
        try:
            obj = (
                JSONData.objects
                .select_related("owner")
                .prefetch_related("shared_users")
                .get(pk=int(object_id))
            )
        except (TypeError, ValueError, JSONData.DoesNotExist):
            return JsonResponse({"error": "Data object not found."}, status=404)

        if not _user_can_access_object(obj, request.user):
            return JsonResponse({"error": "Data object not found."}, status=404)

    answer, suggestions = _build_assistant_answer(question, page, obj=obj)
    return JsonResponse({"answer": answer, "suggestions": suggestions})


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
            "badges": _get_access_badges(obj),
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


def _get_access_badges(obj):
    """
    Return access badges shown in object summaries

    Parameters
    ----------
    obj : JSONData
        Data object to inspect.

    Returns
    -------
    list
        Ordered access labels for display.
    """
    if obj.access_type == "all":
        return ["Public"]

    badges = ["Private"]

    if obj.shared_users.exists():
        badges.append("Shared")

    return badges


def _is_shared_with_user(data, user):
    """
    Return True when the JSON object is explicitly shared with the user
    """
    shared_with = data.get("shared_with", [])

    if not isinstance(shared_with, list):
        return False

    username = (user.username or "").strip().casefold()

    for item in shared_with:
        if not isinstance(item, dict):
            continue

        share_username = str(item.get(SHARE_USERNAME_KEY, "")).strip().casefold()
        if username and username == share_username:
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
    Find a user by username

    Parameters
    ----------
    identifier : str
        Username to look up.

    Returns
    -------
    User or None
        Matching user, when one exists.
    """
    value = (identifier or "").strip()

    if not value:
        return None

    return User.objects.filter(username__iexact=value).first()


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
        "show_bulk_export": True,
    }
    return render(request, "pages/data_list.html", context)


@login_required
@require_POST
def export_selected_my_data_objects_view(request):
    """
    Export selected data objects owned by the current user
    """
    selected_ids = request.POST.getlist("selected_objects")
    exported_objects = []

    for raw_id in selected_ids:
        try:
            object_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        try:
            obj = JSONData.objects.get(pk=object_id, owner=request.user)
        except JSONData.DoesNotExist:
            continue

        exported_objects.append(obj.data or {})

    if not exported_objects:
        messages.error(request, "Select at least one of your data objects to export.")
        return redirect("json_data_list")

    content = json.dumps(exported_objects, indent=2, ensure_ascii=False)
    response = HttpResponse(content, content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="my_data_objects.json"'
    return response


@login_required
@require_POST
def delete_selected_my_data_objects_view(request):
    """
    Delete selected data objects owned by the current user
    """
    selected_ids = request.POST.getlist("selected_objects")
    object_ids = []

    for raw_id in selected_ids:
        try:
            object_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if not object_ids:
        messages.error(request, "Select at least one of your data objects to delete.")
        return redirect("json_data_list")

    data_objects = JSONData.objects.filter(pk__in=object_ids, owner=request.user)
    deleted_count = data_objects.count()

    if deleted_count == 0:
        messages.error(request, "Select at least one of your data objects to delete.")
        return redirect("json_data_list")

    data_objects.delete()
    messages.success(request, f"Deleted {deleted_count} data object(s).")
    return redirect("json_data_list")


def _get_shared_with_me_objects(user):
    """
    Return prepared data objects explicitly shared with one user
    """
    data_objects = (
        JSONData.objects
        .filter(shared_users=user, access_type="c")
        .exclude(owner=user)
        .select_related("owner")
        .prefetch_related("shared_users")
        .order_by("-uploaded_at")
    )

    return [_prepare_list_object(obj) for obj in data_objects]


def _get_share_events(user):
    """
    Return share events created by one user
    """
    return (
        DataNotification.objects
        .filter(
            actor=user,
            notification_type=DataNotification.TYPE_SHARED_DATA,
        )
        .select_related("recipient", "data_object", "data_object__owner")
        .order_by("-created_at")
    )


@login_required
def share_view(request):
    """
    Display incoming and outgoing sharing information
    """
    context = {
        "segment": "share",
        "shared_with_me_objects": _get_shared_with_me_objects(request.user),
        "share_events": _get_share_events(request.user),
    }
    return render(request, "pages/share.html", context)


@login_required
def shared_with_me_view(request):
    """
    Redirect old Shared with Me links to the unified Share page
    """
    return redirect("share")


@login_required
def sharing_history_view(request):
    """
    Redirect old sharing history links to the unified Share page
    """
    return redirect("share")


@login_required
def notification_list_view(request):
    """
    Display notifications for the signed-in user
    """
    notifications = (
        DataNotification.objects
        .filter(recipient=request.user)
        .select_related("actor", "data_object", "data_object__owner")
        .order_by("is_read", "-created_at")
    )

    context = {
        "segment": "notifications",
        "notifications": notifications,
        "unread_count": notifications.filter(is_read=False).count(),
    }
    return render(request, "pages/notifications.html", context)


@login_required
def notification_open_view(request, pk):
    """
    Mark one notification read and open its data object
    """
    notification = get_object_or_404(
        DataNotification.objects.select_related("data_object"),
        pk=pk,
        recipient=request.user,
    )

    if not _user_can_access_object(notification.data_object, request.user):
        raise Http404("Data object not found")

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    return redirect("json_data_detail", pk=notification.data_object_id)


@login_required
@require_POST
def notification_mark_all_read_view(request):
    """
    Mark all notifications read for the signed-in user
    """
    DataNotification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).update(is_read=True)

    messages.success(request, "All notifications marked as read.")
    return redirect("notification_list")


@login_required
def search_view(request):
    """
    Search accessible records using common metadata and optional field conditions

    Preset data fields are available independently of uploaded records. Results
    respect access permissions, and invalid conditions never broaden a search.
    Text queries require every whole word, ignoring order and case. Public
    matches appear first, with the newest uploads first in each group.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request containing optional search parameters.

    Returns
    -------
    HttpResponse
        Search form, preset field choices, matching accessible records, and count.
    """
    keyword = request.GET.get("keyword", "").strip()
    title = request.GET.get("title", "").strip()
    identifier = request.GET.get("identifier", "").strip()
    creator = request.GET.get("creator", "").strip()
    software = request.GET.get("software", "").strip()
    phase = request.GET.get("phase", "").strip()
    keywords_value = request.GET.get("keywords", "").strip()
    owner_name = request.GET.get("owner", "").strip()
    access = request.GET.get("access", "").strip()

    if access not in {"public", "my_private", "my_data", "shared_with_me"}:
        access = ""

    condition_rows, conditions, search_errors = parse_conditions(request.GET)
    advanced_open = any(
        [
            title,
            identifier,
            creator,
            software,
            phase,
            keywords_value,
            owner_name,
            access,
            condition_rows,
            search_errors,
        ]
    )
    search_performed = bool(keyword or advanced_open)
    keyword_terms = _split_keyword_terms(keyword)
    common_queries = {
        "title": title,
        "identifier": identifier,
        "creator": creator,
        "software": software,
        "phase": phase,
        "keywords": keywords_value,
        "owner": owner_name,
    }
    common_terms = {
        key: _split_keyword_terms(value) for key, value in common_queries.items()
    }

    filtered_objects = []
    data_objects = (
        JSONData.objects
        .filter(Q(owner=request.user) | Q(access_type="all") | Q(shared_users=request.user))
        .distinct()
        .select_related("owner")
        .prefetch_related("shared_users")
        .order_by("-uploaded_at", "-pk")
    )
    if not search_performed or search_errors:
        data_objects = data_objects.none()

    for obj in data_objects:
        data = obj.data if isinstance(obj.data, dict) else {}

        specifically_shared = (
            obj.owner_id != request.user.id
            and obj.access_type != "all"
            and any(user.pk == request.user.pk for user in obj.shared_users.all())
        )
        if access == "public" and obj.access_type != "all":
            continue
        if access == "my_data" and obj.owner_id != request.user.id:
            continue
        if access == "my_private":
            if not (obj.owner_id == request.user.id and obj.access_type == "c"):
                continue
        if access == "shared_with_me" and not specifically_shared:
            continue

        if keyword_terms:
            if specifically_shared:
                access_text = "shared with me"
            elif obj.owner_id == request.user.id and obj.access_type == "c":
                access_text = "my private"
            elif obj.access_type == "all":
                access_text = "public"
            else:
                access_text = "shared"
            full_text = _build_basic_search_text(obj, access_text)
            if not matches_whole_words((full_text,), keyword_terms):
                continue

        common_match = True
        for field, terms in common_terms.items():
            if not terms:
                continue
            if field == "owner":
                value = obj.owner.username
            elif field == "creator":
                value = [data.get("creator"), data.get("creator_affiliation")]
            else:
                value = data.get(field)
            text = _normalize_search_value(value)
            if not matches_whole_words((text,), terms):
                common_match = False
                break
        if not common_match or not matches_conditions(data, conditions):
            continue

        filtered_objects.append(_prepare_list_object(obj))

    filtered_objects.sort(key=lambda obj: obj.access_type != "all")

    field_options = [get_field_option(value) for value, label in DATA_FIELD_CHOICES]
    option_labels = {option["value"]: option["label"] for option in field_options}
    for row in condition_rows:
        field = row["field"]
        if field in DATA_FIELD_TYPES and field not in option_labels:
            option = get_field_option(field)
            field_options.append(option)
            option_labels[field] = option["label"]
    operator_labels = dict(OPERATOR_CHOICES)
    option_defaults = {option["value"]: option["default_operator"] for option in field_options}
    if not condition_rows:
        condition_rows = [{"field": "", "operator": "words", "value": "", "value_to": ""}]
    for row in condition_rows:
        row["field_available"] = row["field"] in option_labels
        row["field_label"] = option_labels.get(row["field"], row["field"])
        row["boolean_value"] = DATA_FIELD_TYPES.get(row["field"]) == "boolean"
        row["unit"] = "K" if row["field"] == "global_temperature" else ""
        allowed_operators = get_field_operators(row["field"])
        text_preset = option_defaults.get(row["field"]) == "words"
        row["simple_text"] = text_preset and row["operator"] == "words"
        if text_preset:
            allowed_operators = tuple(
                value for value in allowed_operators if value in {"words", row["operator"]}
            )
        elif not row["field"]:
            allowed_operators = ("words", "eq", "gt", "gte", "lt", "lte", "between")
        row["operator_choices"] = [
            (value, label) for value, label in OPERATOR_CHOICES
            if value in allowed_operators
        ]
        row["operator_available"] = row["operator"] in allowed_operators
        row["operator_label"] = operator_labels.get(row["operator"], row["operator"] or "Choose a comparison")
        row["array_numeric"] = (
            DATA_FIELD_TYPES.get(row["field"]) == "array"
            and row["operator"] not in {"contains", "exact"}
            and row["operator_available"]
        )

    context = {
        "segment": "search",
        "data_objects": filtered_objects,
        "result_count": len(filtered_objects),
        "search_performed": search_performed,
        "keyword": keyword,
        "title": title,
        "identifier": identifier,
        "creator": creator,
        "software": software,
        "phase": phase,
        "keywords_value": keywords_value,
        "owner_name": owner_name,
        "access": access,
        "advanced_open": advanced_open,
        "condition_rows": condition_rows,
        "field_options": field_options,
        "operator_choices": OPERATOR_CHOICES,
        "search_errors": search_errors,
        "max_conditions": MAX_CONDITIONS,
    }
    return render(request, "pages/search.html", context)


@login_required
def search_live_data_objects_view(request):
    """
    Return the latest public data objects for the live activity feed

    Private objects are excluded even when the current user can access them.

    Parameters
    ----------
    request : HttpRequest
        Incoming AJAX request.

    Returns
    -------
    JsonResponse
        Summaries of the twenty most recent public objects and total public count.
    """
    data_objects = (
        JSONData.objects
        .filter(access_type="all")
        .select_related("owner")
        .order_by("-uploaded_at", "-pk")
    )
    total_count = data_objects.count()

    objects = []

    for obj in data_objects[:20]:
        data = obj.data or {}
        uploaded_at = timezone.localtime(obj.uploaded_at)
        display_name = str(data.get("title") or data.get("identifier") or "Object")
        identifier = str(data.get("identifier") or "")

        objects.append(
            {
                "id": obj.id,
                "display_name": display_name,
                "identifier": identifier,
                "owner": obj.owner.username,
                "access": _get_access_display(obj),
                "access_badges": _get_access_badges(obj),
                "uploaded_at": uploaded_at.strftime("%Y-%m-%d %H:%M"),
                "detail_url": reverse("json_data_detail", args=[obj.pk]),
            }
        )

    return JsonResponse({"objects": objects, "total_count": total_count})


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
    - Show short list[number] directly and longer list[number] collapsed
    - Show bool, empty values, and complex arrays without dropping them
    - Recurse into dict and list[dict]
    """
    rows = []

    if isinstance(data, dict):
        if not data:
            rows.append(
                {
                    "label": _format_detail_label(prefix),
                    "type": "json",
                    "summary": "Empty object",
                    "json_value": json.dumps(data, indent=2, ensure_ascii=False),
                }
            )
            return rows

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            rows.extend(_build_detail_rows(value, full_key))
        return rows

    if isinstance(data, list):
        if len(data) == 0:
            rows.append(
                {
                    "label": _format_detail_label(prefix),
                    "type": "json",
                    "summary": "Empty list",
                    "json_value": json.dumps(data, indent=2, ensure_ascii=False),
                }
            )
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
                    "value": data,
                    "count": len(data),
                    "is_inline": len(data) <= SHORT_NUMERIC_ARRAY_INLINE_LIMIT,
                    "json_value": json.dumps(data, indent=2, ensure_ascii=False),
                }
            )
            return rows

        if not all(isinstance(item, dict) for item in data):
            rows.append(
                {
                    "label": _format_detail_label(prefix),
                    "type": "json",
                    "summary": f"Array with {len(data)} item(s)",
                    "json_value": json.dumps(data, indent=2, ensure_ascii=False),
                }
            )
            return rows

        for index, item in enumerate(data):
            item_prefix = f"{prefix}[{index}]"
            rows.extend(_build_detail_rows(item, item_prefix))
        return rows

    if isinstance(data, str):
        if not data.strip():
            rows.append(
                {
                    "label": _format_detail_label(prefix),
                    "type": "empty",
                    "value": "",
                }
            )
            return rows

        rows.append(
            {
                "label": _format_detail_label(prefix),
                "type": "string",
                "value": data,
            }
        )
        return rows

    if isinstance(data, bool):
        rows.append(
            {
                "label": _format_detail_label(prefix),
                "type": "boolean",
                "value": str(data).lower(),
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

    if data is None:
        rows.append(
            {
                "label": _format_detail_label(prefix),
                "type": "empty",
                "value": "",
            }
        )
        return rows

    rows.append(
        {
            "label": _format_detail_label(prefix),
            "type": "json",
            "summary": type(data).__name__,
            "json_value": json.dumps(data, indent=2, ensure_ascii=False, default=str),
        }
    )
    return rows


def _ensure_required_detail_rows(data, rows):
    """
    Add empty placeholders for missing required top-level fields
    """
    if not isinstance(data, dict):
        data = {}

    existing_labels = {row.get("label") for row in rows}
    complete_rows = list(rows)

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field in data or field in existing_labels:
            continue

        complete_rows.append(
            {
                "label": field,
                "type": "empty",
                "value": "",
            }
        )

    return complete_rows


VISUALIZED_DETAIL_FIELD_ROOTS = {
    "mechanical_BC",
    "stress",
    "total_strain",
    "plastic_strain",
}


def _filter_visualized_detail_rows(rows):
    """
    Remove rows that are already represented by detail-page visualizations
    """
    filtered_rows = []

    for row in rows:
        label = str(row.get("label", ""))
        root_label = label.split(" / ", 1)[0]

        if root_label in VISUALIZED_DETAIL_FIELD_ROOTS:
            continue

        filtered_rows.append(row)

    return filtered_rows


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
MECHANICAL_TENSOR_COMPONENTS = ("11", "22", "33", "12", "13", "23")


def _get_plot_variable_unit(key, units):
    """
    Return the unit label for a plot variable
    """
    if not isinstance(units, dict):
        return ""

    if key.startswith("stress_") or key == "equivalent_stress":
        unit = units.get("Stress", "")
    elif key.startswith(("strain_", "plastic_strain_")) or key in {
        "equivalent_total_strain",
        "equivalent_plastic_strain",
    }:
        unit = units.get("Strain", "")
    else:
        unit = ""

    if unit in ("", None):
        return ""

    if unit == 1 or str(unit).strip() == "1":
        return ""

    return str(unit)


def _get_plot_variable_kind(key):
    """
    Return the mechanical variable kind for one plot key
    """
    if key.startswith("stress_") or key == "equivalent_stress":
        return "stress"

    if key.startswith("plastic_strain_") or key == "equivalent_plastic_strain":
        return "plastic_strain"

    if key.startswith("strain_") or key == "equivalent_total_strain":
        return "strain"

    return ""


def _get_plot_component(key):
    """
    Return the tensor component suffix or equivalent marker
    """
    if key.startswith("stress_"):
        return key.replace("stress_", "", 1)

    if key.startswith("plastic_strain_"):
        return key.replace("plastic_strain_", "", 1)

    if key.startswith("strain_"):
        return key.replace("strain_", "", 1)

    if key.startswith("equivalent_"):
        return "equivalent"

    return ""


def _get_plot_symbol_label(key):
    """
    Return an ASCII notation key for one plot variable
    """
    component = _get_plot_component(key)

    if key == "equivalent_stress":
        return "sigma_eq"

    if key == "equivalent_total_strain":
        return "epsilon_eq"

    if key == "equivalent_plastic_strain":
        return "epsilon_p_eq"

    if key.startswith("stress_"):
        return f"sigma_{component}"

    if key.startswith("plastic_strain_"):
        return f"epsilon_p_{component}"

    if key.startswith("strain_"):
        return f"epsilon_{component}"

    return key


def _get_plot_display_label(key):
    """
    Return display notation for one plot variable
    """
    if key == "equivalent_stress":
        return "\u03c3_eq"

    if key == "equivalent_total_strain":
        return "\u03b5_eq"

    if key == "equivalent_plastic_strain":
        return "\u03b5_p,eq"

    component = _get_plot_component(key)

    if key.startswith("stress_"):
        return f"σ_{component}"

    if key.startswith("plastic_strain_"):
        return f"ε_p,{component}"

    if key.startswith("strain_"):
        return f"ε_{component}"

    return key


def _build_plot_variable(full_key, key, values, units):
    """
    Build one template-ready plot variable dictionary
    """
    return {
        "key": full_key,
        "label": _format_plot_variable_label(full_key),
        "short_label": key,
        "symbol_label": _get_plot_symbol_label(key),
        "display_label": _get_plot_display_label(key),
        "kind": _get_plot_variable_kind(key),
        "component": _get_plot_component(key),
        "unit": _get_plot_variable_unit(key, units),
        "values": values,
    }


def _get_component_arrays(group, prefix):
    """
    Return component arrays for a stress or strain tensor group
    """
    if not isinstance(group, dict):
        return None

    arrays = {}

    for component in MECHANICAL_TENSOR_COMPONENTS:
        key = f"{prefix}_{component}"
        value = group.get(key)

        if not _is_numeric_list(value):
            return None

        arrays[component] = value

    return arrays


def _calculate_equivalent_stress(arrays):
    """
    Calculate von Mises equivalent stress values
    """
    count = min(len(values) for values in arrays.values())
    values = []

    for index in range(count):
        s11 = arrays["11"][index]
        s22 = arrays["22"][index]
        s33 = arrays["33"][index]
        s12 = arrays["12"][index]
        s13 = arrays["13"][index]
        s23 = arrays["23"][index]
        equivalent = math.sqrt(
            0.5 * (
                ((s11 - s22) ** 2)
                + ((s22 - s33) ** 2)
                + ((s33 - s11) ** 2)
            )
            + (3 * ((s12 ** 2) + (s13 ** 2) + (s23 ** 2)))
        )
        values.append(equivalent)

    return values


def _calculate_equivalent_strain(arrays):
    """
    Calculate von Mises equivalent strain values
    """
    count = min(len(values) for values in arrays.values())
    values = []

    for index in range(count):
        e11 = arrays["11"][index]
        e22 = arrays["22"][index]
        e33 = arrays["33"][index]
        e12 = arrays["12"][index]
        e13 = arrays["13"][index]
        e23 = arrays["23"][index]
        mean_strain = (e11 + e22 + e33) / 3
        equivalent = math.sqrt(
            (2 / 3) * (
                ((e11 - mean_strain) ** 2)
                + ((e22 - mean_strain) ** 2)
                + ((e33 - mean_strain) ** 2)
                + (2 * ((e12 ** 2) + (e13 ** 2) + (e23 ** 2)))
            )
        )
        values.append(equivalent)

    return values


def _extract_equivalent_plot_variables(data, units):
    """
    Build calculated equivalent stress and strain plot variables
    """
    if not isinstance(data, dict):
        return []

    variables = []
    stress_arrays = _get_component_arrays(data.get("stress"), "stress")
    total_strain_arrays = _get_component_arrays(data.get("total_strain"), "strain")
    plastic_strain_arrays = _get_component_arrays(
        data.get("plastic_strain"),
        "plastic_strain",
    )

    if stress_arrays is not None:
        variables.append(
            _build_plot_variable(
                "stress.equivalent_stress",
                "equivalent_stress",
                _calculate_equivalent_stress(stress_arrays),
                units,
            )
        )

    if total_strain_arrays is not None:
        variables.append(
            _build_plot_variable(
                "total_strain.equivalent_total_strain",
                "equivalent_total_strain",
                _calculate_equivalent_strain(total_strain_arrays),
                units,
            )
        )

    if plastic_strain_arrays is not None:
        variables.append(
            _build_plot_variable(
                "plastic_strain.equivalent_plastic_strain",
                "equivalent_plastic_strain",
                _calculate_equivalent_strain(plastic_strain_arrays),
                units,
            )
        )

    return variables


def _extract_plot_variables(data, prefix="", units=None):
    """
    Recursively extract plot-ready numeric arrays for mechanical variables
    """
    variables = []

    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, list) and _is_numeric_list(value) and key.startswith(PLOT_FIELD_PREFIXES):
                variables.append(_build_plot_variable(full_key, key, value, units))
            else:
                variables.extend(_extract_plot_variables(value, full_key, units))

    elif isinstance(data, list):
        for index, item in enumerate(data):
            item_prefix = f"{prefix}[{index}]"
            variables.extend(_extract_plot_variables(item, item_prefix, units))

    if not prefix:
        variables.extend(_extract_equivalent_plot_variables(data, units))

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


def _format_compact_value(value):
    """
    Return a compact display value for one scalar or list
    """
    if isinstance(value, list):
        if len(value) <= 6:
            return "[" + ", ".join(_format_compact_value(item) for item in value) + "]"

        return f"[{len(value)} values]"

    if _is_number_value(value):
        return f"{value:.4g}"

    if value in (None, ""):
        return ""

    return str(value)


def _normalize_applied_load(load):
    """
    Return display-ready details for one applied load entry
    """
    if not isinstance(load, dict):
        return None

    details = []

    for key in ("magnitude", "frequency", "duration", "R"):
        if key not in load:
            continue

        details.append(
            {
                "key": key,
                "value": load.get(key),
                "display": _format_compact_value(load.get(key)),
            }
        )

    if not details:
        return None

    return {
        "magnitude": load.get("magnitude"),
        "frequency": load.get("frequency"),
        "duration": load.get("duration"),
        "R": load.get("R"),
        "details": details,
        "summary": ", ".join(
            f"{detail['key']}: {detail['display']}"
            for detail in details
            if detail["display"] != ""
        ),
    }


def _get_mechanical_target_type(vertices):
    """
    Return the display target type from normalized vertices
    """
    normalized_vertices = {
        str(vertex).strip().upper()
        for vertex in vertices
        if str(vertex).strip()
    }

    if normalized_vertices == set(MECHANICAL_BC_VERTICES):
        return "Whole cube"

    if len(normalized_vertices) == 4:
        return "Face"

    if len(normalized_vertices) == 2:
        return "Edge"

    return "Point"


def _get_mechanical_target_label(vertices):
    """
    Return a compact target label for a mechanical boundary condition
    """
    target_type = _get_mechanical_target_type(vertices)

    if target_type == "Whole cube":
        return "Whole cube"

    if len(vertices) == 1:
        return vertices[0]

    return " - ".join(vertices)


def _get_load_for_axis(applied_loads, load_index, is_group_target):
    """
    Return the load entry for one loaded axis
    """
    if load_index < len(applied_loads):
        return applied_loads[load_index]

    if is_group_target and len(applied_loads) == 1:
        return applied_loads[0]

    return {}


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

        vertices = [
            str(vertex).strip()
            for vertex in vertices
            if str(vertex).strip()
        ]

        if not vertices:
            continue

        if not isinstance(constraints, list):
            constraints = []

        if not isinstance(applied_loads, list):
            applied_loads = [applied_loads] if isinstance(applied_loads, dict) else []

        load_index = 0
        axes = []
        is_group_target = len(vertices) > 1

        for index, direction in enumerate(MECHANICAL_BC_DIRECTIONS):
            status = ""
            if index < len(constraints):
                status = str(constraints[index]).strip().casefold()

            normalized_load = None

            if status == "loaded":
                load = _get_load_for_axis(applied_loads, load_index, is_group_target)
                normalized_load = _normalize_applied_load(load)
                load_index += 1

            axes.append(
                {
                    "direction": direction,
                    "status": status,
                    "load": normalized_load,
                    "load_details": normalized_load["details"] if normalized_load else [],
                    "load_summary": normalized_load["summary"] if normalized_load else "",
                    "magnitude": normalized_load["magnitude"] if normalized_load else None,
                }
            )

        items.append(
            {
                "vertex": _get_mechanical_target_label(vertices),
                "vertices": vertices,
                "target_type": _get_mechanical_target_type(vertices),
                "axes": axes,
                "loading_type": condition.get("loading_type", ""),
                "loading_mode": condition.get("loading_mode", ""),
            }
        )

    defined_vertices = {
        vertex
        for item in items
        for vertex in item.get("vertices", [])
    }
    free_axes = [
        {
            "direction": direction,
            "status": "free",
            "load": "",
            "load_details": [],
            "load_summary": "",
            "magnitude": None,
        }
        for direction in MECHANICAL_BC_DIRECTIONS
    ]

    for vertex in MECHANICAL_BC_VERTICES:
        if vertex in defined_vertices:
            continue

        items.append(
            {
                "vertex": vertex,
                "vertices": [vertex],
                "target_type": "Point",
                "axes": free_axes,
                "loading_type": "",
                "loading_mode": "",
                "is_defined": False,
            }
        )

    for item in items:
        item.setdefault("is_defined", True)

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
        if obj.access_type == "all":
            messages.error(
                request,
                "Public data objects cannot be shared with specific users. Use Search to find public data.",
            )
            return redirect("json_data_detail", pk=obj.pk)

        username = request.POST.get("share_user", "")
        share_user = _find_share_user(username)

        if share_user is None:
            messages.error(request, "No user was found with that username.")
            return redirect("json_data_detail", pk=obj.pk)

        if share_user == request.user:
            messages.error(request, "You already own this data object.")
            return redirect("json_data_detail", pk=obj.pk)

        was_already_shared = obj.shared_users.filter(pk=share_user.pk).exists()
        obj.shared_users.add(share_user)

        if not was_already_shared:
            _create_shared_data_notification(obj, request.user, share_user)

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

    detail_rows = _ensure_required_detail_rows(
        obj.data or {},
        _build_detail_rows(obj.data or {}),
    )
    detail_rows = _filter_visualized_detail_rows(detail_rows)
    display_rows = [
        row
        for row in detail_rows
        if (
            row["type"] in {
                "string",
                "string_list",
                "number",
                "numeric_array",
                "boolean",
                "empty",
                "json",
            }
        )
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
        detail_breadcrumb_label = "My Data"
    elif _user_has_specific_share(obj, request.user):
        detail_back_url_name = "share"
        detail_back_label = "Back to Share"
        detail_breadcrumb_label = "Share"
    else:
        detail_back_url_name = "search"
        detail_back_label = "Back to Search"
        detail_breadcrumb_label = "Search"

    context = {
        "data_object": obj,
        "detail_rows": display_rows,
        "plot_variables": plot_variables,
        "mechanical_bc_items": mechanical_bc_items,
        "shared_users": obj.shared_users.order_by("username"),
        "detail_back_url_name": detail_back_url_name,
        "detail_back_label": detail_back_label,
        "detail_breadcrumb_label": detail_breadcrumb_label,
    }
    return render(request, "pages/data_detail.html", context)
