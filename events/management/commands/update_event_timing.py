from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event
from events.reminders import remind_ending_events


class Command(BaseCommand):
    help = "Update event statuses and create upcoming end-time reminders."

    def handle(self, *args, **options):
        now = timezone.now()
        Event.refresh_statuses(now=now)
        remind_ending_events(now)
