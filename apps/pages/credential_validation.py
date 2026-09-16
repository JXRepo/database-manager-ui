from copy import copy

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST

from .forms import ORCIDAccountSetupForm, SignUpForm
from .middleware import requires_orcid_account_setup
from .rate_limits import consume_rate_limit, get_client_identifier


CREDENTIAL_FIELDS = ("username", "email", "password1", "password2")
MAX_PREVIEW_REQUEST_BYTES = 32 * 1024
MAX_PREVIEW_FIELD_CHARACTERS = 4096
PREVIEW_SIZE_MESSAGE = (
    "Live validation is unavailable for this input size. "
    "You can still submit the form."
)


@sensitive_variables()
def _credential_errors(form):
    """
    Preview form rules before the password confirmation is complete

    The original form remains authoritative. Strength errors appear beside
    the first password while confirmation errors stay beside the second.

    Parameters
    ----------
    form : SignUpForm or ORCIDAccountSetupForm
        Bound form for the account workflow being previewed.

    Returns
    -------
    dict
        Lists of validation messages keyed by each credential field.
    """
    form.full_clean()
    errors = {}
    for name in CREDENTIAL_FIELDS:
        errors[name] = list(form.errors.get(name, []))

    password = form.cleaned_data.get("password1")
    if password:
        try:
            validate_password(password, form.instance)
        except ValidationError as error:
            for message in error.messages:
                if message not in errors["password1"]:
                    errors["password1"].append(message)
                if message in errors["password2"]:
                    errors["password2"].remove(message)

    return errors


@never_cache
@sensitive_post_parameters()
@require_POST
@csrf_protect
@sensitive_variables()
def validate_account_credentials(request):
    """
    Return bounded credential feedback without saving or authenticating users

    Registration checks never exclude existing users. ORCID setup checks only
    exclude the authenticated account while its initial setup is pending.

    Parameters
    ----------
    request : HttpRequest
        POST containing the workflow mode and unprefixed credential fields.

    Returns
    -------
    JsonResponse
        Field error lists or a general error when preview is unavailable.
    """
    try:
        decision = consume_rate_limit(
            "credential_validation", get_client_identifier(request),
        )
        if not decision.allowed:
            response = JsonResponse(
                {"error": "Too many validation requests. Please try again shortly."},
                status=429,
            )
            response["Retry-After"] = str(decision.retry_after_seconds)
            return response

        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid request size."}, status=400)
        if content_length < 0:
            return JsonResponse({"error": "Invalid request size."}, status=400)
        if content_length > MAX_PREVIEW_REQUEST_BYTES:
            return JsonResponse({"error": PREVIEW_SIZE_MESSAGE}, status=413)

        mode = request.POST.get("mode")
        if mode not in {"register", "orcid_setup"}:
            return JsonResponse({"error": "Invalid validation mode."}, status=400)

        data = {}
        for name in CREDENTIAL_FIELDS:
            value = request.POST.get(name, "")
            if len(value) > MAX_PREVIEW_FIELD_CHARACTERS:
                return JsonResponse({"error": PREVIEW_SIZE_MESSAGE}, status=413)
            data[name] = value

        if mode == "orcid_setup":
            if not requires_orcid_account_setup(request.user):
                return JsonResponse({"error": "Account setup is unavailable."}, status=403)
            form = ORCIDAccountSetupForm(data=data, instance=copy(request.user))
        else:
            form = SignUpForm(data=data)

        return JsonResponse({"errors": _credential_errors(form)})
    except DatabaseError:
        return JsonResponse(
            {"error": "Validation is temporarily unavailable. You can still submit the form."},
            status=503,
        )
