import logging
import unicodedata
from email.utils import parseaddr
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import DatabaseError
from django.http import HttpResponseRedirect
from django.template import loader

from .rate_limits import consume_rate_limit, get_client_identifier

logger = logging.getLogger("django.contrib.auth")


def password_reset_email_available():
    """
    Check sender and transport configuration before looking up an account

    Production never uses a development mail backend or a visitor supplied
    origin for recovery messages.

    Returns
    -------
    bool
        Whether password recovery has a usable delivery configuration.
    """
    try:
        validate_email(parseaddr(settings.DEFAULT_FROM_EMAIL)[1])
        origin = urlsplit(settings.PASSWORD_RESET_BASE_URL)
        if settings.PASSWORD_RESET_BASE_URL or not settings.DEBUG:
            if (
                not origin.hostname
                or origin.port == 0
                or origin.scheme not in ({"http", "https"} if settings.DEBUG else {"https"})
                or origin.username is not None
                or origin.password is not None
                or origin.path not in ("", "/")
                or origin.query
                or origin.fragment
            ):
                return False
    except (ValidationError, ValueError):
        return False

    if settings.EMAIL_BACKEND == "apps.pages.email_backend.ResendEmailBackend":
        return bool(settings.RESEND_API_KEY)
    if settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend":
        return (
            bool(settings.EMAIL_HOST)
            and not (settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL)
            and (settings.DEBUG or settings.EMAIL_USE_TLS or settings.EMAIL_USE_SSL)
        )
    return settings.DEBUG and settings.EMAIL_BACKEND in {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
    }


class StyledPasswordResetForm(PasswordResetForm):
    """
    Collect the saved account email using the existing authentication styling
    """

    email = forms.EmailField(
        label="Email address", max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        """
        Preserve Django's email rendering without logging transport secrets

        Parameters
        ----------
        subject_template_name : str
            Template for the single line email subject.
        email_template_name : str
            Template for the plain text reset instructions.
        context : dict
            Account and token values prepared by Django.
        from_email : str or None
            Sender override, or the configured default sender.
        to_email : str
            Saved recipient address for the eligible account.
        html_email_template_name : str or None
            Optional HTML alternative, as supported by Django's form.
        """
        subject = "".join(loader.render_to_string(subject_template_name, context).splitlines())
        body = loader.render_to_string(email_template_name, context)
        message = EmailMultiAlternatives(subject, body, from_email, [to_email])
        if html_email_template_name is not None:
            message.attach_alternative(loader.render_to_string(html_email_template_name, context), "text/html")
        try:
            message.send()
        except Exception:
            # SMTP diagnostics can contain recipients, credentials or message content.
            logger.error("Password reset email could not be sent; check the email service configuration.")


class StyledSetPasswordForm(SetPasswordForm):
    """
    Style the replacement password fields without changing their validators
    """

    def __init__(self, *args, **kwargs):
        """
        Add the standard input style and password manager hints

        Parameters
        ----------
        *args : tuple
            Positional arguments for Django's form, including the target user.
        **kwargs : dict
            Submitted data and other form options.
        """
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control", "autocomplete": "new-password"})


class PasswordRecoveryView(PasswordResetView):
    """
    Request a password reset with delivery checks and persisted quotas
    """

    form_class = StyledPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"

    def get_context_data(self, **kwargs):
        """
        Explain unavailable recovery before a visitor submits an email

        Parameters
        ----------
        **kwargs : dict
            Context values provided by Django's form view.

        Returns
        -------
        dict
            Form context with the current email delivery availability.
        """
        context = super().get_context_data(**kwargs)
        context["email_available"] = password_reset_email_available()
        return context

    def post(self, request, *args, **kwargs):
        """
        Reject unavailable delivery or excessive requests before account lookup

        Parameters
        ----------
        request : HttpRequest
            Recovery request with the submitted email.
        *args : tuple
            Positional route arguments.
        **kwargs : dict
            Named route arguments.

        Returns
        -------
        HttpResponse
            Form errors, a temporary refusal or the normal request result.
        """
        form = self.get_form()
        if not password_reset_email_available():
            return self.render_to_response(self.get_context_data(form=form), status=503)
        try:
            decision = consume_rate_limit("password_reset", get_client_identifier(request))
        except DatabaseError:
            form.add_error(None, "Password reset is temporarily unavailable. Please try again later.")
            return self.render_to_response(self.get_context_data(form=form), status=503)
        if not decision.allowed:
            form.add_error(None, "Too many reset requests. Please try again later.")
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(decision.retry_after_seconds)
            return response
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        """
        Limit inbox traffic and use the configured origin for reset links

        Parameters
        ----------
        form : StyledPasswordResetForm
            Validated email request.

        Returns
        -------
        HttpResponse
            Neutral acknowledgement or a temporary service error.
        """
        email = unicodedata.normalize("NFKC", form.cleaned_data["email"]).casefold()
        try:
            decision = consume_rate_limit("password_reset_email", email)
        except DatabaseError:
            form.add_error(None, "Password reset is temporarily unavailable. Please try again later.")
            return self.render_to_response(self.get_context_data(form=form), status=503)
        if not decision.allowed:
            return HttpResponseRedirect(self.get_success_url())
        self.extra_email_context = {"site_name": "Materials Simulation Data Platform"}
        if settings.PASSWORD_RESET_BASE_URL:
            origin = urlsplit(settings.PASSWORD_RESET_BASE_URL)
            self.extra_email_context.update({"protocol": origin.scheme, "domain": origin.netloc})
        return super().form_valid(form)


class PasswordRecoveryConfirmView(PasswordResetConfirmView):
    """
    Preserve token checks and reject accounts that are no longer eligible
    """

    form_class = StyledSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"

    def get_user(self, uidb64):
        """
        Resolve an active account that still has a usable password

        Parameters
        ----------
        uidb64 : str
            Account identifier encoded in the reset URL.

        Returns
        -------
        User or None
            Eligible account, or no account for the supplied reset link.
        """
        user = super().get_user(uidb64)
        if user is not None and user.is_active and user.has_usable_password():
            return user
        return None
