# Handle account management and password recovery in the administrator portal.
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from accounts.access import administrator_required
from accounts.email_addresses import EMAIL_IN_USE, accounts_with_email
from accounts.mail_setup import smtp_configuration_error
from accounts.models import Notification, Profile
from accounts.notifications import notify_account

from .audit import record_activity
from .forms import ManagedAccountCreateForm, ManagedAccountEditForm, TemporaryPasswordForm
from .models import ActivityLog

logger = logging.getLogger(__name__)


# Django superusers can manage custom administrator accounts as well as students and organizers.
def managed_account_roles(actor):
    roles = (Profile.Role.STUDENT, Profile.Role.ORGANIZER)
    if actor.is_superuser:
        return (*roles, Profile.Role.ADMIN)
    return roles


# Keep Django staff and superuser accounts under Django's own admin tools.
def managed_accounts(actor):
    return User.objects.filter(
        is_staff=False,
        is_superuser=False,
        profile__role__in=managed_account_roles(actor),
    ).exclude(pk=actor.pk).select_related("profile")


# Apply search, role, and status filters before paging the managed accounts.
@administrator_required
def account_list(request):
    accounts = managed_accounts(request.user).order_by("username")
    roles = managed_account_roles(request.user)
    term = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    if term:
        accounts = accounts.filter(
            # Join the search fields with OR so a match in any one field is enough.
            Q(username__icontains=term) | Q(first_name__icontains=term)
            | Q(last_name__icontains=term) | Q(email__icontains=term)
            | Q(profile__student_id__icontains=term)
        )
    if role in roles:
        accounts = accounts.filter(profile__role=role)
    if status in ("active", "inactive"):
        accounts = accounts.filter(is_active=status == "active")
    return render(request, "administration/accounts.html", {
        "section": "accounts",
        "page_obj": Paginator(accounts, 20).get_page(request.GET.get("page")),
        "search_term": term,
        "role_filter": role,
        "roles": roles,
        "status_filter": status,
    })


# Save the new account and its audit entry together after the form passes validation.
@administrator_required
@never_cache
def account_create(request):
    form = ManagedAccountCreateForm(
        request.POST if request.method == "POST" else None,
        roles=managed_account_roles(request.user),
    )
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        try:
            with transaction.atomic():
                user = form.save()
                record_activity(
                    request.user, ActivityLog.Action.ACCOUNT_CREATED, user.username,
                    user.profile.get_role_display(),
                )
        # A concurrent account creation can claim a value after this form was validated.
        except IntegrityError as error:
            if str(error) == EMAIL_IN_USE:
                form.add_error("email", EMAIL_IN_USE)
            elif User.objects.filter(username=username).exists() or Profile.objects.filter(student_id=username).exists():
                form.add_error("username", "This username or School ID is already in use.")
            else:
                raise
        else:
            messages.success(request, f"Created the account for {user.username}.")
            return redirect("administration:account_detail", pk=user.pk)

    return render(request, "administration/form.html", {
        "section": "accounts", "title": "Create account", "form": form,
        "description": "Students and organizers choose a new password at their first sign-in.",
        "cancel_name": "administration:accounts", "submit_label": "Create account",
    })


# Load one managed account and save changes from its details form.
@administrator_required
@transaction.atomic
def account_detail(request, pk):
    accounts = managed_accounts(request.user)
    if request.method == "POST":
        # Request a database row lock when the account is being edited.
        accounts = accounts.select_for_update()
    user = get_object_or_404(accounts, pk=pk)
    form = ManagedAccountEditForm(request.POST if request.method == "POST" else None, instance=user)
    if request.method == "POST" and form.is_valid():
        try:
            if form.has_changed():
                with transaction.atomic():
                    form.save()
                    record_activity(request.user, ActivityLog.Action.ACCOUNT_UPDATED, user.username)
                messages.success(request, "Account details saved.")
        except IntegrityError as error:
            if str(error) != EMAIL_IN_USE:
                raise
            form.add_error("email", EMAIL_IN_USE)
        else:
            return redirect("administration:account_detail", pk=user.pk)

    return render(request, "administration/account_detail.html", {
        "section": "accounts", "account": user, "form": form,
    })


# Activate or deactivate the account and record the change in the log.
@administrator_required
@require_POST
@transaction.atomic
def account_status(request, pk):
    user = get_object_or_404(managed_accounts(request.user).select_for_update(), pk=pk)
    status = request.POST.get("status")
    if status not in ("active", "inactive"):
        messages.error(request, "Choose a valid account status.")
        return redirect("administration:account_detail", pk=pk)

    active = status == "active"
    if user.is_active != active:
        user.is_active = active
        user.save(update_fields=["is_active"])
        action = ActivityLog.Action.ACCOUNT_ENABLED if active else ActivityLog.Action.ACCOUNT_DISABLED
        record_activity(request.user, action, user.username)
        messages.success(request, f"Account {'activated' if active else 'deactivated'}.")
    return redirect("administration:account_detail", pk=pk)


# Show the deletion impact before saving the deletion and its audit entry together.
@administrator_required
@require_http_methods(["GET", "HEAD", "POST"])
@transaction.atomic
def account_delete(request, pk):
    accounts = managed_accounts(request.user)
    if request.method == "POST":
        accounts = accounts.select_for_update()
    user = get_object_or_404(accounts, pk=pk)
    if request.method == "POST":
        record_activity(
            request.user, ActivityLog.Action.ACCOUNT_DELETED, user.username,
            f"{user.profile.get_role_display()} account #{pk}.",
        )
        user.delete()
        messages.success(request, "Account deleted.")
        return redirect("administration:accounts")

    return render(request, "administration/account_delete.html", {
        "section": "accounts",
        "account": user,
        "attendance_count": user.profile.attendance_records.count(),
        "stamp_count": user.profile.event_stamps.aggregate(total=Sum("quantity", default=0))["total"],
        "event_count": user.organized_events.count(),
    })


# Set a password and notify the account holder about the change.
@administrator_required
@never_cache
@transaction.atomic
def account_password(request, pk):
    accounts = managed_accounts(request.user)
    if request.method == "POST":
        accounts = accounts.select_for_update()
    user = get_object_or_404(accounts, pk=pk)
    is_administrator = user.profile.role == Profile.Role.ADMIN
    form_class = SetPasswordForm if is_administrator else TemporaryPasswordForm
    form = form_class(user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        # The student and organizer password form can require a change at the next sign-in.
        requires_change = form.cleaned_data.get("require_change", False)
        user.profile.must_change_password = requires_change
        user.profile.save(update_fields=["must_change_password"])
        record_activity(
            request.user, ActivityLog.Action.PASSWORD_RESET, user.username,
            "Password change required at the next login." if requires_change else "",
        )
        notify_account(
            user,
            "Your BSIT Events password was changed",
            "A BSIT Events administrator changed your account password. "
            "Contact your administrator for your new password or use Reset password on the sign-in page.",
        )
        messages.success(request, f"Password updated for {user.username}.")
        return redirect("administration:account_detail", pk=pk)

    return render(request, "administration/form.html", {
        "section": "accounts", "title": "Set password" if is_administrator else "Set temporary password",
        "form": form,
        "description": f"Set a new password for {user.username}. Share it with the account holder directly.",
        "cancel_name": "administration:account_detail", "cancel_pk": pk,
        "submit_label": "Set password",
    })


# Send a signed reset link to the managed account's saved email address.
@administrator_required
@require_POST
def account_reset_email(request, pk):
    user = get_object_or_404(managed_accounts(request.user), pk=pk)
    if not user.is_active or not user.email:
        messages.error(request, "A reset link needs an active account with an email address.")
        return redirect("administration:account_detail", pk=pk)
    if accounts_with_email(user.email).exclude(pk=user.pk).exists():
        messages.error(request, "Give this account its own email address before sending a reset link.")
        return redirect("administration:account_detail", pk=pk)

    if setup_error := smtp_configuration_error():
        messages.error(request, setup_error)
        return redirect("administration:account_detail", pk=pk)

    # Supply the encoded user ID, Django token, and public site address to the email
    # templates.
    email_context = {
        "user": user,
        "protocol": "https" if request.is_secure() else "http",
        "domain": request.get_host(),
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": default_token_generator.make_token(user),
        **settings.PASSWORD_RESET_EMAIL_CONTEXT,
    }
    try:
        reset_email = EmailMultiAlternatives(
            "Reset your BSIT Events password",
            render_to_string("accounts/password_reset_email.txt", email_context),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
        # Send an HTML version alongside the plain-text email.
        reset_email.attach_alternative(
            render_to_string("accounts/password_reset_email.html", email_context), "text/html",
        )
        delivered = reset_email.send()
    except Exception:
        logger.exception("Failed to send a password-reset link for user %s", user.pk)
        delivered = 0

    # Create the notice and audit entry after the mail backend accepts the message.
    if delivered:
        with transaction.atomic():
            # The account can be deleted while the mail server is processing the message.
            account = managed_accounts(request.user).select_for_update().filter(pk=pk).first()
            record_activity(request.user, ActivityLog.Action.RESET_LINK_SENT, user.username)
            if account is None:
                messages.info(request, "Reset email sent. The account is no longer available.")
                return redirect("administration:accounts")
            Notification.objects.create(
                user=account,
                subject="Password-reset link requested",
                body="An administrator requested a password-reset link for your account. Check your email.",
            )
        messages.success(request, "Password-reset email sent.")
    else:
        messages.error(request, "The reset email could not be sent. Check the email configuration and try again.")
    return redirect("administration:account_detail", pk=pk)
