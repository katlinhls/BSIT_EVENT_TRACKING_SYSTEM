# Create in-app notifications and send a copy by email when delivery is configured.
import logging

from django.core.mail import send_mail
from django.db import transaction

from .mail_setup import smtp_configuration_error
from .models import Notification

logger = logging.getLogger(__name__)


def notify_account(user, subject, body):
    """Save an in-app notice and send its email after the change commits."""
    Notification.objects.create(user=user, subject=subject, body=body)
    # The inbox message is already saved. Email requires an address and configured sender
    # settings.
    if not user.email or smtp_configuration_error():
        return

    # Send the notification to the account email and log any delivery error.
    def email_notice():
        try:
            send_mail(subject, body, None, [user.email])
        except Exception:
            logger.exception("Failed to deliver an account notification to user %s", user.pk)

    # Wait until the database change commits before sending the email.
    transaction.on_commit(email_notice)
