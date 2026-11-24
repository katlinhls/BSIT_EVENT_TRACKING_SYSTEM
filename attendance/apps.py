# Django app configuration for attendance records and scanning.
from django.apps import AppConfig

# Give Django the app's package name and its default type for record IDs.
class AttendanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendance"
