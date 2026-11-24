# Handle browser requests for account access, registration, profiles, password recovery, and
# notifications.
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.contrib.auth.views import (
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.utils import timezone

from events.models import Event
from events.reminders import remind_event_ending, schedule_refresh_delay

from .access import account_role, dashboard_name
from .email_addresses import EMAIL_IN_USE
from .forms import AccountPasswordResetForm, ProfileForm, StudentRegistrationForm
from .mail_setup import smtp_configuration_error
from .models import Notification, Profile


# Use one sign-in flow for both landing-page panels and require the role for the selected
# panel.
def _role_login(request, role):
    if request.user.is_authenticated:
        return redirect(dashboard_name(request.user))

    username = request.POST.get("username", "").strip()
    if request.method == "POST":
        # Django compares the submitted credentials with the saved password hash.
        user = authenticate(request, username=username, password=request.POST.get("password"))
        if user and account_role(user) == role:
            login(request, user)
            return redirect(dashboard_name(user))
        messages.error(request, f"Invalid {role.lower()} username or password.")

    return render(request, "home.html", {
        "login_role": role,
        "login_username": username,
    })


# Open the student sign-in panel and send successful sign-ins to the student dashboard.
@never_cache
def student_login(request):
    return _role_login(request, Profile.Role.STUDENT)


# Open the organizer sign-in panel for accounts with the organizer role.
@never_cache
def organizer_login(request):
    return _role_login(request, Profile.Role.ORGANIZER)


# Display the registration form on GET and create the student account after a valid POST.
def register_student(request):
    if request.user.is_authenticated:
        return redirect(dashboard_name(request.user))

    form = StudentRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        school_id = form.cleaned_data["student_id"]
        try:
            # Save the user and linked profile together so registration completes as one
            # operation.
            with transaction.atomic():
                form.save()
        # Show the appropriate field error when a concurrent request saved the same value.
        except IntegrityError as error:
            if str(error) == EMAIL_IN_USE:
                form.add_error("email", EMAIL_IN_USE)
            elif User.objects.filter(username=school_id).exists() or Profile.objects.filter(student_id=school_id).exists():
                form.add_error("student_id", "This School ID is already registered.")
            else:
                raise
        else:
            messages.success(request, "Account created. Sign in with your School ID.")
            return redirect("accounts:student_login")

    return render(request, "accounts/register.html", {"form": form})


# Send a signed-in user to the dashboard selected by their role.
@login_required
def dashboard(request):
    return redirect(dashboard_name(request.user))


# End the current session after the sign-out form submits a POST.
@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("home")


# Bind the current user's profile and any uploaded image to the settings form.
@login_required
def profile(request):
    role = account_role(request.user)
    if role not in (Profile.Role.STUDENT, Profile.Role.ORGANIZER):
        raise PermissionDenied

    profile = request.user.profile
    form = ProfileForm(
        request.POST if request.method == "POST" else None,
        # Uploaded photos arrive separately from the text fields in the form.
        request.FILES if request.method == "POST" else None,
        instance=profile,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError as error:
            if str(error) != EMAIL_IN_USE:
                raise
            form.add_error("email", EMAIL_IN_USE)
        else:
            messages.success(request, "Profile updated successfully.")
            return redirect("accounts:profile")

    return render(request, "accounts/profile.html", {
        "form": form,
        "profile": profile,
        "dashboard_route": dashboard_name(request.user),
    })


# Ask an account with a temporary password to choose a new one before continuing.
@login_required
@never_cache
def required_password(request):
    role = account_role(request.user)
    if role not in (Profile.Role.STUDENT, Profile.Role.ORGANIZER):
        raise PermissionDenied
    if not request.user.profile.must_change_password:
        return redirect(dashboard_name(request.user))

    form = SetPasswordForm(request.user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        new_password = form.cleaned_data["new_password1"]
        if check_password(new_password, request.user.password):
            form.add_error("new_password1", "Choose a password different from the temporary password.")
        else:
            with transaction.atomic():
                # Read the latest account and profile inside the transaction before changing
                # the password.
                current_user = User.objects.select_for_update().get(pk=request.user.pk)
                current_profile = Profile.objects.select_for_update().get(user=current_user)
                # End the session if the stored password changed during this request.
                if current_user.password != request.user.password:
                    logout(request)
                    return redirect("home")
                current_user.set_password(new_password)
                current_user.save(update_fields=["password"])
                current_profile.must_change_password = False
                current_profile.save(update_fields=["must_change_password"])
            # Refresh the session with the new password hash so the user can continue signed
            # in.
            update_session_auth_hash(request, current_user)
            messages.success(request, "Your new password has been saved.")
            return redirect(dashboard_name(request.user))

    return render(request, "accounts/required_password.html", {"form": form})


# Use Django's signed-in password change form and return to the profile after saving.
class AccountPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    # Queue a success notice and let Django save the new password.
    def form_valid(self, form):
        messages.success(self.request, "Your password has been changed.")
        return super().form_valid(form)


# Use Django's email-based reset flow with the BSIT form and email templates.
class AccountPasswordResetView(PasswordResetView):
    form_class = AccountPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    html_email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    # Check SMTP setup before Django tries to send the reset email.
    def form_valid(self, form):
        if smtp_configuration_error():
            form.add_error(None, "Password reset email is unavailable. Contact your BSIT Events administrator.")
            return self.form_invalid(form)
        # Use the configured public address when building the reset link.
        self.extra_email_context = settings.PASSWORD_RESET_EMAIL_CONTEXT
        return super().form_valid(form)


# Show a general confirmation after a reset request is processed.
class AccountPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


# Open the new-password form for a valid reset link.
class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    # Save a new password and clear the required-change flag in the same transaction.
    def form_valid(self, form):
        with transaction.atomic():
            if (
                Profile.objects.filter(user=self.user, must_change_password=True).exists()
                and check_password(form.cleaned_data["new_password1"], self.user.password)
            ):
                form.add_error("new_password1", "Choose a password different from the temporary password.")
                return self.form_invalid(form)
            response = super().form_valid(form)
            Profile.objects.filter(user=self.user).update(must_change_password=False)
        return response


# Show a brief confirmation before returning to the homepage.
class AccountPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


# Show only the signed-in user's inbox, with paging and a POST to mark notices as read.
@login_required
def notifications(request):
    role = account_role(request.user)
    if role not in (Profile.Role.STUDENT, Profile.Role.ORGANIZER):
        raise PermissionDenied
    inbox = Notification.objects.filter(user=request.user)
    if request.method == "POST":
        inbox.filter(is_read=False).update(is_read=True)
        return redirect("accounts:notifications")
    if role == Profile.Role.STUDENT:
        page = Paginator(inbox, 20).get_page(request.GET.get("page"))
        return render(request, "accounts/notifications.html", {"page_obj": page})

    now = timezone.now()
    Event.refresh_statuses(now=now)
    events = list(Event.objects.filter(
        organizer=request.user, status__in=(Event.Status.UPCOMING, Event.Status.ONGOING),
    ))
    # Only the current reminder for an editable event can offer an end-time change.
    ending_at = {event.pk: event.ends_at for event in events if remind_event_ending(event, now)}
    page = Paginator(inbox, 20).get_page(request.GET.get("page"))
    for notice in page:
        notice.can_extend = notice.event_end_at is not None and ending_at.get(notice.event_id) == notice.event_end_at
    return render(request, "events/organizer_notifications.html", {
        "page_obj": page,
        "organizer_section": "notifications",
        "refresh_after_ms": schedule_refresh_delay(events, now),
    })
