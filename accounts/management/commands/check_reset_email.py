# Run this with python manage.py check_reset_email to diagnose Gmail or other SMTP delivery.
from smtplib import SMTPAuthenticationError, SMTPException

from django.conf import settings
from django.core.mail import get_connection
from django.core.management.base import BaseCommand, CommandError

from accounts.mail_setup import smtp_configuration_error


# Django discovers a management command from its filename and runs this Command class.
class Command(BaseCommand):
    help = "Check the password-reset SMTP connection and link origin without sending email."

    # Validate the settings, test the connection, and display the address used for reset
    # links.
    def handle(self, *args, **options):
        if setup_error := smtp_configuration_error():
            raise CommandError(setup_error)

        is_gmail = settings.EMAIL_HOST.lower() == "smtp.gmail.com"

        try:
            # Opening the connection tests the SMTP login. The context manager closes it when
            # finished.
            with get_connection():
                pass
        # Report authentication failures by their SMTP code and point to the required
        # credentials.
        except SMTPAuthenticationError as error:
            credentials = "the Gmail address and Google App Password" if is_gmail else "the SMTP credentials"
            raise CommandError(f"SMTP sign-in rejected (code {error.smtp_code}). Check {credentials} in .env.") from None
        except (OSError, SMTPException) as error:
            raise CommandError(
                f"SMTP connection failed ({type(error).__name__}). Check EMAIL_HOST, EMAIL_PORT, TLS, and your host's SMTP access."
            ) from None

        self.stdout.write(self.style.SUCCESS("SMTP connection and configured authentication succeeded."))
        # Show the fixed link origin if one is configured for this deployment.
        origin = settings.PASSWORD_RESET_EMAIL_CONTEXT
        if origin.get("domain"):
            self.stdout.write(f"Reset link origin is {origin['protocol']}://{origin['domain']}.")
        else:
            self.stdout.write("Reset links use the host where the reset was requested. Set PASSWORD_RESET_ORIGIN to use a fixed site address.")
