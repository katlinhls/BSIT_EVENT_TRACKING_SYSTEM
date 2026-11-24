# Let administrators review attendance and correct recorded times with an audit trail.
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.vary import vary_on_headers

from accounts.access import administrator_required
from accounts.notifications import notify_account
from attendance.live import live_attendance_response
from attendance.models import Attendance
from attendance.reporting import event_attendance_records, parse_attendance_day
from attendance.services import sync_attendance_stamp
from events.models import Event

from .audit import record_activity
from .forms import AttendanceCorrectionForm, attendance_version
from .models import ActivityLog


# List events with counts for time-ins and completed attendance.
@administrator_required
def event_index(request):
    term = request.GET.get("q", "").strip()
    events = Event.objects.annotate(
        checked_in=Count("attendance_records", filter=Q(attendance_records__in_at__isnull=False)),
        completed=Count("attendance_records", filter=Q(
            attendance_records__in_at__isnull=False, attendance_records__out_at__isnull=False,
        )),
    ).order_by("-date", "-start_time", "-pk")
    if term:
        events = events.filter(Q(name__icontains=term) | Q(venue__icontains=term))
    return render(request, "administration/attendance_events.html", {
        "section": "attendance",
        "page_obj": Paginator(events, 20).get_page(request.GET.get("page")),
        "search_term": term,
    })


# Show the attendance for one event and allow student searches within that event.
@administrator_required
@vary_on_headers("Accept")
def event_records(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    records = event_attendance_records(event).order_by("student__student_id", "attendance_date", "pk")
    try:
        day = parse_attendance_day(event, request.GET.get("day"))
    except ValueError as error:
        raise Http404("Choose a day within the event schedule.") from error
    if day:
        records = records.filter(attendance_date=day)
    term = request.GET.get("q", "").strip()
    if term:
        records = records.filter(
            Q(student__student_id__icontains=term) | Q(student__user__username__icontains=term)
            | Q(student__user__first_name__icontains=term) | Q(student__user__last_name__icontains=term)
        )
    context = {
        "section": "attendance", "event": event,
        "page_obj": Paginator(records, 25).get_page(request.GET.get("page")),
        "search_term": term,
        "selected_day": day,
    }
    if request.method == "GET" and request.headers.get("Accept") == "application/json":
        return live_attendance_response(request, context, {
            "rows": "administration/partials/attendance_record_rows.html",
            "pagination": "administration/partials/pagination.html",
        })
    return render(request, "administration/attendance_records.html", context)


# Apply the corrected times and keep the stamp, audit entry, and inbox notice in sync.
def _save_correction(request, event, record, form):
    data = form.cleaned_data
    time_in, time_out = data["time_in"], data["time_out"]
    excused = data["excused_time_out"]
    # Detect a newer edit before overwriting a record from an older form.
    if record is not None and data["version"] != attendance_version(record):
        form.add_error(None, "This record changed while you were editing it. Reload the record and try again.")
        return False

    record = record or form.checkout_record
    existing_record = record is not None
    if not existing_record:
        record = Attendance(event=event, student=data["student"], attendance_date=data["attendance_date"])

    # Record checkout type changes even when both timestamps stay the same.
    changes = {}
    if record.excused_time_out != excused:
        changes["Time Out type"] = {
            "before": "Excused Time Out" if record.excused_time_out else ("Time Out" if record.out_at else None),
            "after": "Excused Time Out" if excused else ("Time Out" if time_out else None),
        }
        record.excused_time_out = excused

    for field, label, new_value in (
        ("in_at", "Time in", time_in),
        ("out_at", "Time out", time_out),
    ):
        previous = getattr(record, field)
        if previous != new_value:
            changes[label] = {
                "before": previous.isoformat() if previous else None,
                "after": new_value.isoformat() if new_value else None,
            }
            setattr(record, field, new_value)
            # Clear scanner attribution when an administrator manually replaces that
            # timestamp.
            setattr(record, field.replace("_at", "_scanned_by"), None)

    if not changes:
        form.add_error(None, "Change a time or the Time Out type before saving.")
        return False

    try:
        with transaction.atomic():
            # Save the record and its related changes inside the same transaction.
            record.save()
            sync_attendance_stamp(record)
            record_activity(
                request.user, ActivityLog.Action.ATTENDANCE_CORRECTED,
                f"{event.name} · {record.attendance_date:%Y-%m-%d} · {record.student.display_name} ({record.student.student_id or record.student.user.username})",
                data["reason"], changes,
            )
            notify_account(
                record.student.user,
                "Your BSIT Events attendance was updated",
                f"An administrator updated your attendance for {event.name}. "
                "Open Event History in your student dashboard to review your records.",
            )
    # Show a form error if a competing request already created this student's record.
    except IntegrityError:
        if existing_record or not Attendance.objects.filter(
            event=event, student=record.student, attendance_date=record.attendance_date,
        ).exists():
            raise
        form.add_error("student", "This student already has a record for this day. Open it to make a correction.")
        return False

    messages.success(request, "Attendance saved and recorded in the activity log.")
    return True


# Handle both the add-record form and the edit form for a record in the selected event.
@administrator_required
@transaction.atomic
def correct(request, event_id, record_id=None):
    # Use the same lock order as the scanner while recording a correction and its award.
    events = Event.objects.select_for_update() if request.method == "POST" else Event.objects.all()
    event = get_object_or_404(events, pk=event_id)
    record = None
    if record_id is not None:
        records = event.attendance_records.all()
        if request.method == "POST":
            # Request a row lock for an existing record while its correction is saved.
            records = records.select_for_update()
        record = get_object_or_404(records, pk=record_id)

    try:
        day = parse_attendance_day(event, request.GET.get("day"))
    except ValueError as error:
        raise Http404("Choose a day within the event schedule.") from error
    form = AttendanceCorrectionForm(
        request.POST if request.method == "POST" else None, record=record, event=event,
        initial={"attendance_date": day or event.attendance_date_at(timezone.now())},
    )
    if request.method == "POST" and form.is_valid() and _save_correction(request, event, record, form):
        query = {"day": day.isoformat()} if day else None
        return redirect(reverse("administration:attendance_records", args=[event.pk], query=query))

    return render(request, "administration/attendance_correct.html", {
        "section": "attendance", "form": form, "event": event, "record": record,
        "timezone": timezone.get_current_timezone_name(),
    })
