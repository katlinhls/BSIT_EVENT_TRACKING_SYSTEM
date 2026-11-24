# Django app configuration for student dashboards and earned stamps.
from django.apps import AppConfig

# Give Django the app's package name and its default type for record IDs.
class StampsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stamps"
