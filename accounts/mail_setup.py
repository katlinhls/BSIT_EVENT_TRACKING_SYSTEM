# Check the mail configuration before a view tries to contact the SMTP server.
from django.conf import settings


def smtp_configuration_error():
    """Return a message when the configured SMTP sender cannot send email."""
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        return "Configure Django to send email over SMTP."
    # Gmail delivery needs a sender account, an App Password, and an encrypted connection.
    if settings.EMAIL_HOST.lower() == "smtp.gmail.com":
        if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
            return "Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env to the Gmail address and its App Password."
        if not (settings.EMAIL_USE_TLS or settings.EMAIL_USE_SSL):
            return "Enable TLS for Gmail SMTP with EMAIL_USE_TLS=1."
    # A missing error message means these settings passed the local checks.
    return None
