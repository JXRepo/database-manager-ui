from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .models import AccountProfile


def getting_started_context(request):
    """
    Offer the introduction until the current account acknowledges it

    Rendering a page never creates a profile or consumes the introduction.
    The application layout supplies the dialog after account setup is complete.

    Parameters
    ----------
    request : HttpRequest
        Request whose user and route determine the initial display.

    Returns
    -------
    dict
        Saved acknowledgement and automatic display flags for the templates.
    """
    if not request.user.is_authenticated:
        return {}
    route_name = request.resolver_match.url_name if request.resolver_match else None
    if route_name in {"login", "register", "orcid_setup_credentials"}:
        return {}

    dismissed = AccountProfile.objects.filter(
        user=request.user, getting_started_dismissed_at__isnull=False
    ).exists()
    return {
        "getting_started_dismissed": dismissed,
        "show_getting_started": not dismissed and route_name != "getting_started",
    }


@login_required
@require_http_methods(["GET", "POST"])
def getting_started_view(request):
    """
    Display help or save the current account's acknowledgement

    Ordinary forms work without JavaScript. Enhanced dialog submissions receive
    a confirmation only after the preference has been saved.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request for help or acknowledgement.

    Returns
    -------
    HttpResponse
        Help page, JSON confirmation, or redirect to a safe local destination.
    """
    if request.method == "GET":
        return render(request, "pages/getting_started.html")

    profile, _ = AccountProfile.objects.get_or_create(user=request.user)
    AccountProfile.objects.filter(
        pk=profile.pk, getting_started_dismissed_at__isnull=True
    ).update(getting_started_dismissed_at=timezone.now())

    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"dismissed": True})

    next_url = request.POST.get("next", "")
    if (
        not next_url.startswith("/")
        or "\\" in next_url
        or not url_has_allowed_host_and_scheme(next_url, allowed_hosts=set())
    ):
        next_url = reverse("search")
    return redirect(next_url)
