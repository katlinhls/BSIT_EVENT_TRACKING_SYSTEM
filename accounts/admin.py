# Configure Django's built-in admin so authorized staff can find profiles by school ID, role,
# and linked account name.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import User

from .email_addresses import clean_account_email
from .models import Profile


# Apply the same email check when a Django superuser edits a user.
class AccountUserChangeForm(UserChangeForm):
    def clean_email(self):
        return clean_account_email(self.cleaned_data["email"], self.instance)


admin.site.unregister(User)


@admin.register(User)
class AccountUserAdmin(UserAdmin):
    form = AccountUserChangeForm


# Register this model with columns, filters, and searchable fields for its admin list.
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("student_id", "display_name", "role", "program", "year_level", "must_change_password")
    list_filter = ("role", "program", "year_level")
    search_fields = ("student_id", "user__username", "user__first_name", "user__last_name")
