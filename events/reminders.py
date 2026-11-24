# Create one organizer reminder for each scheduled end that reaches the final five minutes.
from datetime import timedelta
from math import ceil

from django.utils import timezone
from django.utils.formats import date_format

from accounts.models import Notification, Profile
from .models import Event


def remind_event_ending(event, now):
    if (
        not event.organizer_id or event.status == Event.Status.CANCELLED
        or not event.time_out_opens_at <= now < event.ends_at
    ):
        return False
    end_time = date_format(timezone.localtime(event.ends_at), "M j, g:i a")
    Notification.objects.get_or_create(
        user_id=event.organizer_id,
        event=event,
        event_end_at=event.ends_at,
        defaults={
            "subject": "Event ending soon",
            "body": f"{event.name} is scheduled to end at {end_time}. If it is still running, extend the end time from the event page.",
        },
    )
    return True


def remind_ending_events(now, *, organizer=None):
    events = Event.objects.filter(
        status=Event.Status.ONGOING, organizer__is_active=True,
        organizer__profile__role=Profile.Role.ORGANIZER,
    )
    if organizer is not None:
        events = events.filter(organizer=organizer)
    for event in events:
        remind_event_ending(event, now)


def schedule_refresh_delay(events, now):
    """Refresh open workspaces when a status, reminder, or pending checkout can change."""
    transitions = []
    for event in events:
        if event.status not in {Event.Status.UPCOMING, Event.Status.ONGOING}:
            continue
        day = event.attendance_date_at(now)
        session = event.attendance_session(day)
        if session.ends_at <= now and day < event.last_attendance_date:
            session = event.attendance_session(day + timedelta(days=1))
        transitions.extend((event.starts_at, event.time_out_opens_at, session.ends_at, event.ends_at))
        if event.time_out_opens_at <= now < event.ends_at:
            minutes_left = ceil((event.ends_at - now).total_seconds() / 60)
            transitions.append(event.ends_at - timedelta(minutes=minutes_left - 1))
    next_transition = min((value for value in transitions if value > now), default=None)
    return ceil((next_transition - now).total_seconds() * 1000) if next_transition else None
