# Django app configuration for event schedules and organizer pages.
from django.apps import AppConfig

# Give Django the app's package name and its default type for record IDs.
class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "events"
