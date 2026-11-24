# Forms validate registration and profile details before the views save a User or Profile.
from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator

from .email_addresses import accounts_with_email, clean_account_email
from .models import Profile


# Build the selectable combinations from year 1 through 4 and sections A through C.
YEAR_SECTIONS = tuple(
    (f"{year}{section}", f"{year}{section}")
    for year in range(1, 5)
    for section in "ABC"
)

# Collect the login details and student information in one form.
class StudentRegistrationForm(forms.ModelForm):
    student_id = forms.CharField(
        max_length=50,
        label="School ID",
        validators=[UnicodeUsernameValidator()],
        widget=forms.TextInput(attrs={
            "placeholder": "024A-000000",
            "autocomplete": "username",
            "autocapitalize": "none",
            "spellcheck": "false",
        }),
    )
    middle_initial = forms.CharField(
        max_length=1,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "M"}),
    )
    year_level = forms.ChoiceField(
        label="Year and section",
        choices=[("", "Select year and section"), *YEAR_SECTIONS],
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "juan@example.com"}),
    )
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "given-name", "placeholder": "Juan"}),
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "family-name", "placeholder": "Dela Cruz"}),
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Create a password"}),
        min_length=8,
        help_text="Use at least 8 characters.",
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Re-enter your password"}),
    )

    # Connect the name fields to Django's User model. The save method handles the extra
    # fields.
    class Meta:
        model = User
        fields = ["first_name", "last_name"]

    # Normalize the school ID and check both tables that use it as an identifier.
    def clean_student_id(self):
        student_id = self.cleaned_data["student_id"].strip()
        if Profile.objects.filter(student_id=student_id).exists() or User.objects.filter(username=student_id).exists():
            raise forms.ValidationError("This School ID is already registered.")
        return student_id

    # Trim the optional middle initial and store it in uppercase.
    def clean_middle_initial(self):
        return self.cleaned_data.get("middle_initial", "").strip().upper()

    def clean_email(self):
        return clean_account_email(self.cleaned_data["email"])

    # Compare the passwords and run Django's password rules with the proposed account details.
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        if password:
            # Build an unsaved user so password validators can compare the password with their
            # details.
            account = User(
                username=cleaned_data.get("student_id", ""),
                first_name=cleaned_data.get("first_name", ""),
                last_name=cleaned_data.get("last_name", ""),
                email=cleaned_data.get("email", ""),
            )
            try:
                validate_password(password, account)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return cleaned_data

    # Hash the password and create the linked student profile when the user is saved.
    def save(self, commit=True):
        user = super().save(commit=False)
        school_id = self.cleaned_data["student_id"]
        # School ID is the student's login username.
        user.username = school_id
        user.set_password(self.cleaned_data["password"])
        user.email = self.cleaned_data["email"]

        if commit:
            user.save()
            Profile.objects.create(
                user=user,
                role=Profile.Role.STUDENT,
                student_id=school_id,
                middle_initial=self.cleaned_data.get("middle_initial", ""),
                program="BSIT",
                year_level=self.cleaned_data["year_level"],
            )
        return user


# Define the two fields used to collect login credentials.
class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


# Skip password recovery when a legacy address still belongs to multiple accounts.
class AccountPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        if accounts_with_email(email).count() == 1:
            return super().get_users(email)
        return ()


# Edit profile fields together with the name and email stored on the linked User.
class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150, required=False,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    email = forms.EmailField(
        required=False,
        help_text="Password-reset links are sent to this address.",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    # Choose the Profile fields and configure the image picker used for the photo preview.
    class Meta:
        model = Profile
        fields = ["student_id", "middle_initial", "program", "year_level", "profile_image"]
        widgets = {"profile_image": forms.FileInput(attrs={"accept": "image/*", "data-profile-photo": ""})}

    # Pre-fill account fields and adapt the available profile fields to the user's role.
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

            profile = getattr(user, "profile", None)
            if profile and profile.role == Profile.Role.ORGANIZER:
                # Organizer profiles do not need student-specific fields.
                for field_name in ("student_id", "program", "year_level"):
                    self.fields.pop(field_name, None)
            elif profile and profile.role == Profile.Role.STUDENT:
                # School ID is the student's username, so it should not be
                # independently edited and allowed to drift out of sync.
                self.fields["student_id"].disabled = True

    def clean_email(self):
        return clean_account_email(self.cleaned_data["email"], self.user)

    # Write the changed fields to their own tables so untouched values stay as entered.
    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            if self.user:
                user_changes = [
                    field for field in ("first_name", "last_name", "email")
                    if field in self.changed_data
                ]
                for field in user_changes:
                    setattr(self.user, field, self.cleaned_data[field])
                if user_changes:
                    self.user.save(update_fields=user_changes)
            # Save profile fields after the account email passes the database check.
            profile_changes = [field for field in self._meta.fields if field in self.changed_data]
            if profile_changes:
                profile.save(update_fields=profile_changes)
        return profile
