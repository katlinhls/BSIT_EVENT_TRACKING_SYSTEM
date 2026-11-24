# Django app configuration for account and profile features.
from django.apps import AppConfig

# Give Django the app's package name and its default type for record IDs.
class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
