# Build the attendance counts and chart data used by both dashboards.
from django.db.models import Count, Q

from attendance.models import Attendance

from .forms import AnalyticsFilterForm


# Summarize time-ins and completions for the events the caller is allowed to view.
def attendance_summary(events, parameters, *, group_by_program=False):
    # Validate the optional event filter against the supplied event list.
    filters = AnalyticsFilterForm(parameters, events=events, label_suffix="")
    if filters.is_valid() and (event := filters.cleaned_data["event"]):
        events = events.filter(pk=event.pk)

    # Group by the student's year and section, with program labels in the organizer view.
    groups = ("student__program", "student__year_level") if group_by_program else ("student__year_level",)
    sections = list(
        Attendance.objects.filter(event__in=events, in_at__isnull=False)
        .values(*groups)
        .annotate(checked_in=Count("pk"), completed=Count("pk", filter=Q(out_at__isnull=False)))
        .order_by(*groups)
    )
    # Calculate each group's completion percentage from its own time-ins.
    for section in sections:
        section["rate"] = round(section["completed"] * 100 / section["checked_in"], 1)

    # Add the group counts to get the totals for the attendance breakdown.
    checked_in = sum(section["checked_in"] for section in sections)
    completed = sum(section["completed"] for section in sections)
    return {
        "filters": filters,
        "event_count": events.count(),
        "checked_in": checked_in,
        "completed": completed,
        "time_in_only": checked_in - completed,
        # Use a missing value when there are no time-ins so the chart can show an empty rate.
        "completion_rate": round(completed * 100 / checked_in, 1) if checked_in else None,
        "sections": sections,
    }
