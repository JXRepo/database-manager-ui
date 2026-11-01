import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class EmailDeliveryError(Exception):
    """
    Report delivery failure without exposing provider credentials or mail content
    """


class ResendEmailBackend(BaseEmailBackend):
    """
    Deliver plain text account emails through Resend's HTTPS API
    """

    def send_messages(self, email_messages):
        """
        Send account messages without redirects or automatic retries

        Parameters
        ----------
        email_messages : iterable of EmailMessage
            Plain text messages prepared by Django's password recovery form.

        Returns
        -------
        int
            Number of messages accepted by the provider.

        Raises
        ------
        EmailDeliveryError
            Configuration is missing or the provider did not accept a message.
        """
        sent = 0
        for message in email_messages:
            response = None
            try:
                if not settings.RESEND_API_KEY or not message.from_email:
                    raise EmailDeliveryError("Email delivery is not configured.")
                response = requests.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json={
                        "from": message.from_email,
                        "to": message.to,
                        "subject": message.subject,
                        "text": message.body,
                    },
                    timeout=settings.EMAIL_TIMEOUT,
                    allow_redirects=False,
                )
                if response.status_code != 200:
                    raise EmailDeliveryError("Email provider did not accept the message.")
                payload = response.json()
                if not isinstance(payload, dict) or not payload.get("id"):
                    raise EmailDeliveryError("Email provider did not confirm acceptance.")
                sent += 1
            except (requests.RequestException, ValueError, EmailDeliveryError):
                if not self.fail_silently:
                    raise EmailDeliveryError("Password reset email could not be sent.") from None
            finally:
                if response is not None:
                    response.close()
        return sent
