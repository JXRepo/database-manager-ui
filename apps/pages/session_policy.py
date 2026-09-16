import math
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin


SESSION_DEADLINE_KEY = "login_expires_at"
SESSION_REMEMBER_KEY = "login_remember_me"
DEFAULT_LOGIN_AGE = 30 * 24 * 60 * 60
REMEMBERED_SESSION_AGE = 365 * 24 * 60 * 60
RENEWAL_INTERVAL = 24 * 60 * 60


def apply_login_session_policy(request, remember_me=False, *, browser_session=False):
    """
    Start a persistent login or a short browser session for admin authentication

    Ordinary logins expire after thirty days. Remembered logins can renew on
    normal page visits, while admin login retains its shorter fixed deadline.

    Parameters
    ----------
    request : HttpRequest
        Request carrying the authenticated session.
    remember_me : bool
        Whether the user explicitly chose to renew their login as they use it.
    browser_session : bool
        Whether to use the short browser session reserved for admin login.
    """
    if browser_session:
        age = settings.SESSION_COOKIE_AGE
        remember_me = False
    else:
        age = REMEMBERED_SESSION_AGE if remember_me else DEFAULT_LOGIN_AGE
    deadline = timezone.now() + timedelta(seconds=age)
    request.session[SESSION_DEADLINE_KEY] = deadline.timestamp()
    request.session[SESSION_REMEMBER_KEY] = remember_me
    request.session.set_expiry(0 if browser_session else deadline)


class LoginSessionExpiryMiddleware(MiddlewareMixin):
    """
    Enforce login deadlines before protected views or ORCID onboarding
    """

    def process_request(self, request):
        """
        Invalidate expired sessions even if the browser retains their cookie

        Existing sessions without policy metadata receive the ordinary default
        once. Expired sessions cannot become eligible for renewal again.

        Parameters
        ----------
        request : HttpRequest
            Request whose user has been resolved by authentication middleware.
        """
        if not request.user.is_authenticated:
            return

        if SESSION_DEADLINE_KEY not in request.session:
            apply_login_session_policy(request)
            return

        deadline = request.session[SESSION_DEADLINE_KEY]
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or timezone.now().timestamp() >= deadline
            or not isinstance(request.session.get(SESSION_REMEMBER_KEY, False), bool)
        ):
            logout(request)

    def process_response(self, request, response):
        """
        Renew remembered logins on successful page visits at most once per day

        JSON polling, AJAX calls, redirects, and failed requests do not count
        as normal use. The session middleware saves the new cookie and expiry.

        Parameters
        ----------
        request : HttpRequest
            Request after its view has finished processing.
        response : HttpResponse
            Response whose content distinguishes a page visit from polling.

        Returns
        -------
        HttpResponse
            Unchanged response with any renewal stored in the session.
        """
        if (
            not request.user.is_authenticated
            or request.session.get(SESSION_REMEMBER_KEY) is not True
            or request.method != "GET"
            or response.status_code != 200
            or not response.get("Content-Type", "").startswith("text/html")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        ):
            return response

        now = timezone.now()
        deadline = request.session[SESSION_DEADLINE_KEY]
        remaining = deadline - now.timestamp()
        if 0 < remaining <= REMEMBERED_SESSION_AGE - RENEWAL_INTERVAL:
            new_deadline = now + timedelta(seconds=REMEMBERED_SESSION_AGE)
            request.session[SESSION_DEADLINE_KEY] = new_deadline.timestamp()
            request.session.set_expiry(new_deadline)
        return response
