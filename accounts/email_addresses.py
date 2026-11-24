# Share the email check across registration, profile settings, and account management.
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim


EMAIL_IN_USE = "This email address is already used by another account."


def accounts_with_email(email):
    """Find matching accounts without treating capitalization as a different address."""
    return User.objects.alias(email_key=Lower(Trim("email"))).filter(
        email_key=email.strip().lower(),
    )


def clean_account_email(email, account=None):
    email = email.strip()
    if not email:
        return email

    matches = accounts_with_email(email)
    if account and account.pk:
        # A legacy account can keep its saved address when editing unrelated fields.
        if email.lower() == account.email.strip().lower():
            return email
        matches = matches.exclude(pk=account.pk)
    if matches.exists():
        raise ValidationError(EMAIL_IN_USE)
    return email
