# Validate administrator sign-in, managed accounts, and manual attendance corrections.
from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.access import is_portal_admin
from accounts.email_addresses import clean_account_email
from accounts.forms import YEAR_SECTIONS
from accounts.models import Profile


# Extend Django's sign-in form for the management portal.
class AdministratorLoginForm(AuthenticationForm):
    # Require the administrator role after Django checks the submitted credentials.
    def confirm_login_allowed(self, user):
        if not is_portal_admin(user):
            raise self.get_invalid_login_error()


# Confirm the password of the administrator who is already signed in.
class EarlyTimeOutApprovalForm(forms.Form):
    password = forms.CharField(
        label="Administrator password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    @sensitive_variables()
    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError("The password is incorrect.")


# Add role and student details to Django's user creation form.
class ManagedAccountCreateForm(UserCreationForm):
    role = forms.ChoiceField()
    email = forms.EmailField(required=False)
    middle_initial = forms.CharField(max_length=1, required=False)
    year_level = forms.ChoiceField(
        label="Year and section", choices=[("", "Select year and section"), *YEAR_SECTIONS],
        required=False,
    )

    # Use the User account fields and label the student username as their school ID.
    class Meta(UserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email")
        labels = {"username": "Username or School ID"}
        help_texts = {"username": "For students, enter their School ID."}

    # Use the roles available to the signed-in administrator for display and validation.
    def __init__(self, *args, roles, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [(role, role.label) for role in roles]
        self.fields["password1"].label = "Initial password"
        self.fields["password2"].label = "Confirm initial password"
        self.fields["year_level"].help_text = "Required for students."
        self.order_fields([
            "role", "username", "first_name", "last_name", "middle_initial", "email",
            "year_level", "password1", "password2",
        ])

    # Check the school ID stored on profiles as well as Django's username rules.
    def clean_username(self):
        username = super().clean_username()
        if Profile.objects.filter(student_id__iexact=username).exists():
            raise forms.ValidationError("This School ID is already in use.")
        return username

    def clean_email(self):
        return clean_account_email(self.cleaned_data["email"])

    # Require a valid year and section when creating a student account.
    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") == Profile.Role.STUDENT:
            if len(cleaned.get("username", "")) > 50:
                self.add_error("username", "Use at most 50 characters for the School ID.")
            if not cleaned.get("year_level"):
                self.add_error("year_level", "Select a year and section for this student.")
        return cleaned

    # Create the profile and require a new password at sign-in for students and organizers.
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            role = self.cleaned_data["role"]
            student = role == Profile.Role.STUDENT
            Profile.objects.create(
                user=user,
                role=role,
                student_id=user.username if student else None,
                program="BSIT" if student else "",
                year_level=self.cleaned_data["year_level"] if student else "",
                middle_initial=self.cleaned_data["middle_initial"].upper(),
                must_change_password=role != Profile.Role.ADMIN,
            )
        return user


# Limit account editing to name and email fields.
class ManagedAccountEditForm(forms.ModelForm):
    # Use these columns from the User model in the account details form.
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        return clean_account_email(self.cleaned_data["email"], self.instance)

    # Write only the changed values when the form is saved.
    def save(self, commit=True):
        user = super().save(commit=False)
        if commit and self.changed_data:
            user.save(update_fields=self.changed_data)
        return user


# Reuse Django's password rules and let the administrator require a change at the next login.
class TemporaryPasswordForm(SetPasswordForm):
    require_change = forms.BooleanField(
        label="Require a password change at the next login",
        required=False,
        initial=True,
    )

    # Label both entries so the administrator knows which password they are setting.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Temporary password"
        self.fields["new_password2"].label = "Confirm temporary password"


# Include the checkout type so an older form cannot overwrite a newer excuse.
def attendance_version(record):
    return "|".join((
        str(record.pk),
        record.in_at.isoformat() if record.in_at else "",
        record.out_at.isoformat() if record.out_at else "",
        str(int(record.excused_time_out)),
    ))


# Collect a student or existing record, the corrected times, and a reason for the log.
class AttendanceCorrectionForm(forms.Form):
    TIME_IN = "IN"
    TIME_OUT = "OUT"
    EXCUSED_TIME_OUT = "EXCUSED_OUT"
    RECORD_TYPES = (
        (TIME_IN, "Time In"),
        (TIME_OUT, "Time Out"),
        (EXCUSED_TIME_OUT, "Excused Time Out"),
    )

    student = forms.ModelChoiceField(queryset=Profile.objects.none())
    attendance_date = forms.DateField(label="Attendance day")
    record_type = forms.ChoiceField(label="Record type", choices=RECORD_TYPES, initial=TIME_IN, required=False)
    time_in = forms.DateTimeField(label="Time In", required=False)
    time_out = forms.DateTimeField(label="Time Out", required=False)
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    # Carry the version shown when the form opened to detect later edits.
    version = forms.CharField(widget=forms.HiddenInput)

    # Pre-fill existing times or show a student picker when adding attendance.
    def __init__(self, *args, event, record=None, **kwargs):
        self.record = record
        self.checkout_record = None
        self.event = event
        super().__init__(*args, **kwargs)
        for field_name in ("time_in", "time_out"):
            self.fields[field_name].widget = forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M:%S", attrs={"type": "datetime-local", "step": 1},
            )
        self.fields["reason"].help_text = "Explain the correction for the activity log."
        if record:
            del self.fields["student"]
            checkout_type = self.fields["record_type"]
            checkout_type.label = "Time Out type"
            checkout_type.choices = self.RECORD_TYPES[1:]
            checkout_type.help_text = "Applies when a Time Out is saved."
            self.initial.update(
                record_type=self.EXCUSED_TIME_OUT if record.excused_time_out else self.TIME_OUT,
                time_in=timezone.localtime(record.in_at) if record.in_at else None,
                time_out=timezone.localtime(record.out_at) if record.out_at else None,
                version=attendance_version(record),
            )
        else:
            # New records use the student picker. Existing records use their saved student.
            del self.fields["version"]
            self.fields["student"].queryset = Profile.objects.filter(
                role=Profile.Role.STUDENT,
            ).select_related("user").order_by("student_id", "user__username")
            self.fields["time_in"].help_text = "For a checkout, leave blank to use the student's saved Time In."
        if record or event.attendance_day_count == 1:
            del self.fields["attendance_date"]
        else:
            self.fields["attendance_date"].widget = forms.DateInput(format="%Y-%m-%d", attrs={
                "type": "date", "min": event.date.isoformat(), "max": event.last_attendance_date.isoformat(),
            })

    def _prepare_new_record(self, cleaned, day):
        # Older forms submit timestamps without a record type.
        record_type = cleaned["record_type"] or (self.TIME_OUT if cleaned["time_out"] else self.TIME_IN)
        cleaned["record_type"] = record_type
        if record_type == self.TIME_IN:
            if cleaned["time_out"]:
                self.add_error("record_type", "Choose Time Out or Excused Time Out to save a checkout.")
            return
        if not cleaned["time_out"]:
            self.add_error("time_out", "Enter the student's Time Out.")
            return

        # The view locks the event first, as the scanner does.
        self.checkout_record = (
            self.event.attendance_records.select_for_update()
            .filter(student=cleaned["student"], attendance_date=day)
            .first()
        )
        if self.checkout_record is None:
            return
        if self.checkout_record.out_at:
            self.add_error("student", "This student already has a Time Out for this day. Open Correct to change it.")
            return

        saved_time_in = self.checkout_record.in_at
        if saved_time_in is None:
            return
        entered_time_in = cleaned["time_in"]
        if entered_time_in and entered_time_in.replace(microsecond=0) != saved_time_in.replace(microsecond=0):
            self.add_error("time_in", "Leave Time In blank to use the saved time, or open Correct to change it.")
        else:
            cleaned["time_in"] = saved_time_in

    # Keep unchanged timestamp precision and check that time out follows a valid time in.
    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        day = self.record.attendance_date if self.record else cleaned.get("attendance_date", self.event.date)
        if "attendance_date" in self.fields and not self.event.date <= day <= self.event.last_attendance_date:
            self.add_error("attendance_date", "Choose a day within the event schedule.")
            return cleaned

        if self.record:
            # datetime-local displays seconds, so retain the original scan precision
            # when the administrator leaves a timestamp unchanged.
            for field_name, original in (
                ("time_in", self.record.in_at), ("time_out", self.record.out_at),
            ):
                if original and cleaned[field_name] == original.replace(microsecond=0):
                    cleaned[field_name] = original
            if not cleaned["record_type"] and self.record.excused_time_out:
                cleaned["record_type"] = self.EXCUSED_TIME_OUT
        else:
            self._prepare_new_record(cleaned, day)
            if self.errors:
                return cleaned

        time_in, time_out = cleaned["time_in"], cleaned["time_out"]
        if not self.record and not time_in:
            self.add_error("time_in", "Enter a Time In for this student and day.")
        elif time_out and (not time_in or time_out < time_in):
            self.add_error("time_out", "Time out requires a time in and must be at or after it.")
        elif self.record and not time_out and cleaned["record_type"] == self.EXCUSED_TIME_OUT:
            if not self.record.excused_time_out:
                self.add_error("time_out", "Enter a Time Out to mark it excused.")

        if self.event.attendance_day_count > 1 and time_in:
            local_time_in = timezone.localtime(time_in, timezone.get_default_timezone())
            session = self.event.attendance_session(day)
            in_session = day <= local_time_in.date() and time_in < session.ends_at
            original_record = self.record or self.checkout_record
            original_time = original_record.in_at if original_record else None
            if not in_session and time_in != original_time:
                self.add_error("time_in", "Enter a Time In on the selected attendance day before it ends.")

        cleaned["attendance_date"] = day
        cleaned["excused_time_out"] = bool(time_in and time_out and cleaned["record_type"] == self.EXCUSED_TIME_OUT)
        return cleaned
