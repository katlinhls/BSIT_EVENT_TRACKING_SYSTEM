# Read attendance dates and calculate each student's progress across a program.
from datetime import date

from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .models import Attendance


def parse_attendance_day(event, value):
    if not value:
        return None
    day = date.fromisoformat(value)
    if not event.date <= day <= event.last_attendance_date:
        raise ValueError("Choose a day within the event schedule.")
    return day


def event_attendance_records(event):
    records = event.attendance_records.select_related("student__user")
    if event.attendance_day_count == 1:
        return records
    completed_days = (
        Attendance.completed_days(event).filter(student_id=OuterRef("student_id"))
        .order_by().values("student_id").annotate(total=Count("pk")).values("total")
    )
    return records.annotate(days_completed=Coalesce(Subquery(completed_days), 0))
