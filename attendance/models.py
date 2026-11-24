# Define each student's attendance record for a scheduled event day.
from django.db import models
from accounts.models import Profile
from events.models import Event

# Store time in, time out, and the accounts that recorded the two scans.
class Attendance(models.Model):
    student = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="attendance_records")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attendance_records")
    attendance_date = models.DateField()
    # The time-out column can stay empty while a student is still checked in.
    in_at = models.DateTimeField(null=True, blank=True)
    out_at = models.DateTimeField(null=True, blank=True)
    excused_time_out = models.BooleanField(default=False)
    # Save the scanner accounts separately so a record keeps its times if an account is
    # deleted.
    in_scanned_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_in_scans"
    )
    out_scanned_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_out_scans"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Enforce one attendance row per student, event, and day.
    class Meta:
        indexes = [models.Index(fields=["event", "attendance_date"], name="attendance_event_day_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "event", "attendance_date"],
                name="unique_student_event_day_attendance",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(excused_time_out=False)
                    | models.Q(in_at__isnull=False, out_at__isnull=False)
                ),
                name="excused_time_out_requires_both_times",
            ),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # Older callers can still create an attendance record without passing a date.
        if self.attendance_date is None:
            scan_time = self.in_at or self.out_at
            self.attendance_date = self.event.attendance_date_at(scan_time) if scan_time else self.event.date
        super().save(*args, **kwargs)

    @classmethod
    def awaiting_time_out(cls, now):
        # Only records with an existing Time In can be finished after the event.
        return cls.objects.filter(in_at__lte=now, out_at__isnull=True)

    @classmethod
    def checked_in_records(cls, student, now):
        # Match each pending Time Out to the event's current scheduled attendance day.
        pending = (
            cls.awaiting_time_out(now).filter(student=student).select_related("event")
            .only(
                "event", "attendance_date", "in_at", "event__name", "event__venue",
                "event__date", "event__end_date", "event__start_time", "event__end_time",
            )
            .order_by("-in_at", "event_id")
        )
        return [
            record for record in pending
            if record.attendance_date == record.event.attendance_date_at(now)
        ]

    @classmethod
    def checked_in_event_ids(cls, student, now):
        return {record.event_id for record in cls.checked_in_records(student, now)}

    @classmethod
    def completed_days(cls, event):
        return cls.objects.filter(
            event=event, attendance_date__range=event.attendance_date_range,
            in_at__isnull=False, out_at__isnull=False,
        )

    # Treat attendance as complete once both times are saved.
    @property
    def completed(self):
        return self.in_at is not None and self.out_at is not None

    # Convert the stored times into a status for the lists and Excel export.
    @property
    def status(self):
        if self.completed:
            return "EXCUSED" if self.excused_time_out else "COMPLETED"
        if self.in_at:
            return "IN"
        return "PENDING"

    # Label an attendance row with the student's display name and the event.
    def __str__(self):
        return f"{self.student.display_name} - {self.event.name} ({self.attendance_date})"
