from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from .models import AccountProfile


def requires_orcid_account_setup(user):
    """
    Identify verified ORCID accounts that still need initial local credentials

    Ordinary password accounts bypass the profile query entirely.

    Parameters
    ----------
    user : User or AnonymousUser
        Account resolved from the current authenticated session.

    Returns
    -------
    bool
        Whether application access must wait for username and password setup.
    """
    if not user.is_authenticated or not user.is_active or user.has_usable_password():
        return False
    return (
        AccountProfile.objects.filter(
            user_id=user.pk, authenticated_orcid__isnull=False
        )
        .exclude(authenticated_orcid="")
        .exists()
    )


class ORCIDAccountSetupMiddleware(MiddlewareMixin):
    """
    Restrict unfinished ORCID accounts to initial setup and logout
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Redirect protected requests after authentication and CSRF checks

        Existing sessions are checked too, so the modal cannot be bypassed with
        a direct request. Authentication parameters and submitted actions are
        never carried forward as onboarding return targets.

        Parameters
        ----------
        request : HttpRequest
            Incoming request with its resolved user and route.
        view_func : callable
            Resolved view that would otherwise handle the request.
        view_args : tuple
            Positional arguments for the resolved view.
        view_kwargs : dict
            Keyword arguments for the resolved view.

        Returns
        -------
        HttpResponseRedirect or None
            Setup redirect, or no intervention for an allowed request.
        """
        if not requires_orcid_account_setup(request.user):
            return None
        if request.resolver_match.view_name in {
            "orcid_setup_credentials",
            "logout",
            "admin:logout",
        }:
            return None

        next_url = reverse("search")
        authentication_path = request.path.startswith(
            ("/login/", "/register/", "/accounts/", "/settings/orcid/", "/admin/login/")
        )
        authentication_parameters = {
            "code", "state", "username", "password", "client_id", "client_secret",
            "access_token", "id_token", "token", "redirect_uri", "scope", "response_type",
        }
        if (
            request.method == "GET"
            and not authentication_path
            and not authentication_parameters.intersection(request.GET)
        ):
            next_url = request.get_full_path()

        setup_url = reverse("orcid_setup_credentials")
        return redirect(f"{setup_url}?{urlencode({'next': next_url})}")
