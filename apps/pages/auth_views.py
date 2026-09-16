from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.db import DatabaseError
from django.http import Http404, HttpResponse

from .forms import SignInForm
from .rate_limits import consume_rate_limit, get_client_identifier
from .session_policy import apply_login_session_policy


def _password_login_limit_response(request):
    """
    Return a blocking response when a password login cannot proceed

    Parameters
    ----------
    request : HttpRequest
        Incoming password login request.

    Returns
    -------
    HttpResponse or None
        Rate limit response, service error, or None when login may continue.
    """
    username = request.POST.get("username", "").strip().casefold()
    identifier = f"{get_client_identifier(request)}:{username}"

    try:
        decision = consume_rate_limit("password_login", identifier)
    except DatabaseError:
        return HttpResponse("Service unavailable.", status=503)

    if not decision.allowed:
        response = HttpResponse("Too many requests.", status=429)
        response["Retry-After"] = str(decision.retry_after_seconds)
        return response

    return None


def rate_limited_admin_login(request):
    """
    Apply the password limit before Django's admin login view

    Parameters
    ----------
    request : HttpRequest
        Incoming admin login request.

    Returns
    -------
    HttpResponse
        Standard admin response or a generic limiting response.
    """
    if request.method == "POST":
        limit_response = _password_login_limit_response(request)
        if limit_response is not None:
            return limit_response

    response = admin.site.login(request)
    if (
        request.method == "POST"
        and response.status_code == 302
        and request.user.is_authenticated
    ):
        apply_login_session_policy(request, browser_session=True)
    return response


def pilot_disabled_auth_view(request, *args, **kwargs):
    """
    Return not found for authentication features disabled in the pilot

    Parameters
    ----------
    request : HttpRequest
        Incoming request for a disabled route.
    *args : tuple
        Positional route values.
    **kwargs : dict
        Named route values.

    Raises
    ------
    Http404
        Always raised so the disabled route is not exposed.
    """
    raise Http404


class RateLimitedLoginView(LoginView):
    """
    Apply the password login limit before authentication
    """

    authentication_form = SignInForm
    template_name = "accounts/login.html"

    def post(self, request, *args, **kwargs):
        """
        Consume one scoped attempt before processing the login form

        Parameters
        ----------
        request : HttpRequest
            Incoming login request.
        *args : tuple
            Positional arguments supplied by Django.
        **kwargs : dict
            Keyword arguments supplied by Django.

        Returns
        -------
        HttpResponse
            Login response, rate limit denial, or service error.
        """
        limit_response = _password_login_limit_response(request)
        if limit_response is not None:
            return limit_response

        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """
        Apply the remember choice only after a successful password login

        The normal login flow retains Django's session rotation and redirect
        checks before setting the new session lifetime.

        Parameters
        ----------
        form : SignInForm
            Validated credentials and the optional remember choice.

        Returns
        -------
        HttpResponseRedirect
            Redirect returned by the normal successful login flow.
        """
        response = super().form_valid(form)
        apply_login_session_policy(
            self.request,
            remember_me=form.cleaned_data["remember_me"],
        )
        return response
