from django.utils.deprecation import MiddlewareMixin


UPLOAD_NAVIGATION_VIEWS = frozenset({
    "index", "search", "upload_json", "json_data_list", "json_data_detail",
    "json_data_sharing", "share", "shared_with_me", "sharing_history",
    "notification_list", "charts", "account_settings", "getting_started",
})


class UploadNavigationMiddleware(MiddlewareMixin):
    """
    Allow authenticated application pages inside the upload navigation host

    Credential, administration and non HTML responses retain the global frame
    denial policy. Same origin frames still run each page's ordinary scripts.
    """

    def process_response(self, request, response):
        """
        Narrowly permit same origin embedding for successful application pages

        Parameters
        ----------
        request : HttpRequest
            Request after authentication and route resolution.
        response : HttpResponse
            View response before the default clickjacking policy is applied.

        Returns
        -------
        HttpResponse
            Response with an explicit policy only for eligible application pages.
        """
        match = getattr(request, "resolver_match", None)
        user = getattr(request, "user", None)
        if (
            match is not None
            and match.view_name in UPLOAD_NAVIGATION_VIEWS
            and user is not None
            and user.is_authenticated
            and response.status_code == 200
            and response.get("Content-Type", "").startswith("text/html")
        ):
            response["X-Frame-Options"] = "SAMEORIGIN"
        return response
