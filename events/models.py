# Define scheduled events, organizer assignments, and the event status rules.
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

TIME_OUT_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class AttendanceSession:
    day: date
    starts_at: datetime
    ends_at: datetime

    @property
    def time_out_opens_at(self):
        return max(self.starts_at, self.ends_at - TIME_OUT_WINDOW)


# Store the schedule, venue, optional images, and assigned organizer for an event.
class Event(models.Model):
    # Keep the saved status codes and their display labels together.
    class Status(models.TextChoices):
        UPCOMING = "UPCOMING", "Upcoming"
        ONGOING = "ONGOING", "Ongoing"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class TimeOut(models.TextChoices):
        FUTURE_DAY = "future_day"
        WAITING = "waiting"
        LOCKED = "locked"
        APPROVED = "approved"
        OPEN = "open"
        AFTER_END = "after_end"
        CLOSED = "closed"

        @property
        def allows_time_in(self):
            return self in {self.WAITING, self.LOCKED, self.APPROVED, self.OPEN}

        @property
        def allows_time_out(self):
            return self in {self.APPROVED, self.OPEN, self.AFTER_END}

        @property
        def allows_excused_time_out(self):
            return self in {self.LOCKED, self.APPROVED, self.OPEN}

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True, default=None,
        help_text="Set the final date for a multi-day program. Leave blank for a same-day or overnight event.",
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    stamps_per_student = models.PositiveIntegerField(
        default=1,
        help_text="Awarded after Time In and Time Out. Enter 0 for an event without stamps.",
    )
    venue = models.CharField(max_length=200)
    # Keep the venue name useful on its own and store a map pin when one is selected.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    # Keep the event record if the organizer account is removed.
    organizer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organized_events",
    )
    image = models.ImageField(upload_to="events/", null=True, blank=True)
    stamp_design = models.ImageField(upload_to="stamps/", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
    early_time_out_until = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # List later dates and start times first unless a view requests another order.
    class Meta:
        ordering = ["-date", "-start_time"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(
                        latitude__isnull=False, latitude__range=(-90, 90),
                        longitude__isnull=False, longitude__range=(-180, 180),
                    )
                ),
                name="event_valid_map_pin",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(end_date__isnull=True)
                    | models.Q(end_date__gt=models.F("date"))
                    | models.Q(end_date=models.F("date"), end_time__gte=models.F("start_time"))
                ),
                name="event_valid_end_date",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if (self.latitude is None) != (self.longitude is None):
            missing_field = "latitude" if self.latitude is None else "longitude"
            errors[missing_field] = "Enter both coordinates to save a map pin."
        if self.date and self.end_date:
            if self.end_date < self.date:
                errors["end_date"] = "End date must be on or after the start date."
            elif self.end_date == self.date and self.start_time and self.end_time and self.end_time < self.start_time:
                errors["end_time"] = "Choose a later end time or set the end date to the following day."
        if self.pk and not errors and self.date and self.start_time and self.end_time:
            if self.attendance_records.exclude(attendance_date__range=self.attendance_date_range).exists():
                errors["end_date"] = "Keep previously recorded attendance days within the event schedule."
        if errors:
            raise ValidationError(errors)

    @property
    def has_map_pin(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def google_maps_url(self):
        if self.has_map_pin:
            query = f"{self.latitude},{self.longitude}"
        else:
            query = self.venue.strip()
        if not query:
            return ""
        return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": query})

    @property
    def starts_at(self):
        return timezone.make_aware(
            datetime.combine(self.date, self.start_time), timezone.get_default_timezone(),
        )

    @property
    def scheduled_end_date(self):
        if self.end_date is not None:
            return self.end_date
        # Preserve the next-day end of overnight events with no explicit end date.
        if self.end_time < self.start_time:
            return self.date + timedelta(days=1)
        return self.date

    @property
    def ends_at(self):
        return timezone.make_aware(
            datetime.combine(self.scheduled_end_date, self.end_time), timezone.get_default_timezone(),
        )

    @property
    def time_out_opens_at(self):
        return self.attendance_session(self.last_attendance_date).time_out_opens_at

    @property
    def attendance_overnight(self):
        # Equal times on a date range represent a full day per session.
        return self.end_time < self.start_time or (
            self.end_time == self.start_time and self.end_date is not None and self.end_date > self.date
        )

    @property
    def last_attendance_date(self):
        if self.end_date is None or self.end_date == self.date:
            return self.date
        if self.attendance_overnight:
            return self.end_date - timedelta(days=1)
        return self.end_date

    @property
    def attendance_date_range(self):
        return self.date, self.last_attendance_date

    @property
    def attendance_day_count(self):
        return (self.last_attendance_date - self.date).days + 1

    def attendance_date_at(self, now):
        local_now = timezone.localtime(now, timezone.get_default_timezone())
        day = local_now.date()
        # Keep scans after midnight on the date the overnight session began.
        if self.attendance_overnight and local_now.time() < self.end_time:
            day -= timedelta(days=1)
        return max(self.date, min(day, self.last_attendance_date))

    def attendance_session(self, day):
        zone = timezone.get_default_timezone()
        end_day = day + timedelta(days=1) if self.attendance_overnight else day
        return AttendanceSession(
            day=day,
            starts_at=timezone.make_aware(datetime.combine(day, self.start_time), zone),
            ends_at=timezone.make_aware(datetime.combine(end_day, self.end_time), zone),
        )

    @classmethod
    def refresh_statuses(cls, *, now=None):
        """Update event statuses using the full start and end schedule."""
        now = now or timezone.now()
        today = timezone.localdate(now, timezone.get_default_timezone())
        yesterday = today - timedelta(days=1)
        active = cls.objects.exclude(status=cls.Status.CANCELLED)
        active.filter(
            models.Q(end_date__lt=today)
            | models.Q(end_date__isnull=True, date__lt=yesterday)
        ).exclude(
            status=cls.Status.COMPLETED
        ).update(status=cls.Status.COMPLETED)
        active.filter(date__gt=today).exclude(
            status=cls.Status.UPCOMING
        ).update(status=cls.Status.UPCOMING)
        # Recheck programs still in progress, even when they started days ago.
        for event in active.filter(
            models.Q(date__lte=today, end_date__gte=today)
            | models.Q(end_date__isnull=True, date__range=(yesterday, today))
        ).only(
            "date", "end_date", "start_time", "end_time", "status",
        ):
            event.sync_status(now=now)

    def status_at(self, now):
        if self.status == self.Status.CANCELLED:
            return self.status
        if now >= self.ends_at:
            return self.Status.COMPLETED
        if now >= self.starts_at:
            return self.Status.ONGOING
        return self.Status.UPCOMING

    def time_out_state(self, now, session=None):
        if self.status == self.Status.CANCELLED:
            return self.TimeOut.CLOSED
        if session is None:
            session = self.attendance_session(self.attendance_date_at(now))
        if now >= session.ends_at:
            # Finished sessions can still record Time Out for existing check-ins.
            return self.TimeOut.AFTER_END
        if now < session.starts_at:
            today = timezone.localdate(now, timezone.get_default_timezone())
            if self.attendance_day_count > 1 and session.day > today:
                return self.TimeOut.FUTURE_DAY
            return self.TimeOut.WAITING
        if now >= session.time_out_opens_at:
            return self.TimeOut.OPEN
        if self.early_time_out_until and now < self.early_time_out_until:
            return self.TimeOut.APPROVED
        return self.TimeOut.LOCKED

    @property
    def effective_status(self):
        return self.status_at(timezone.now())

    @property
    def is_completed(self):
        return self.effective_status == self.Status.COMPLETED

    def sync_status(self, save=True, *, now=None):
        new_status = self.status_at(now or timezone.now())
        old_status = self.status
        if old_status != new_status:
            self.status = new_status
            # Skip stale writes if another request changed the schedule or status.
            if save and self.pk:
                type(self).objects.filter(
                    pk=self.pk, date=self.date, start_time=self.start_time,
                    end_date=self.end_date, end_time=self.end_time, status=old_status,
                ).update(status=new_status)

        return self.status

    # Display the event name when Django needs a readable label.
    def __str__(self):
        return self.name
