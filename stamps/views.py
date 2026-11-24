# Build the student's dashboard and generate the image for their rotating attendance QR.
import io
from collections import defaultdict

import qrcode
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.access import account_role
from accounts.models import Profile
from attendance.models import Attendance
from attendance.services import create_qr_token, qr_token_expiry
from events.models import Event
from .models import EventStamp

STAMP_CARD_SLOTS = 10


# Keep ten visible slots while preserving the total when a student earns more.
def _stamp_card(profile):
    awards = EventStamp.objects.filter(student=profile)
    stamps_earned = awards.aggregate(total=Sum("quantity", default=0))["total"]
    stamp_slots = []
    # Use one slot per stamp and cap the displayed slots independently of the total.
    for award in awards.select_related("event")[:STAMP_CARD_SLOTS]:
        available = STAMP_CARD_SLOTS - len(stamp_slots)
        stamp_slots.extend([award] * min(award.quantity, available))
        if len(stamp_slots) == STAMP_CARD_SLOTS:
            break
    stamp_slots.extend([None] * (STAMP_CARD_SLOTS - len(stamp_slots)))
    return {"stamps_earned": stamps_earned, "stamp_slots": stamp_slots}


# Use the same history data for the overview, stamp card, and history screens.
def _event_history(profile):
    # Past events are shown in the student's event history.  We keep events
    # without an attendance record so the student can see an ABSENT status.
    past_events = list(
        Event.objects
        .filter(status=Event.Status.COMPLETED)
        .order_by("-date", "-start_time")[:8]
    )

    attendance_by_event = defaultdict(list)
    records = Attendance.objects.filter(student=profile, event__in=past_events).order_by("attendance_date")
    for record in records:
        attendance_by_event[record.event_id].append(record)

    # Keep the daily scans and the overall status for each program in the student's history.
    event_history = []
    for event in past_events:
        records = attendance_by_event[event.pk]
        attendance = records[0] if records else None
        completed_days = sum(
            record.completed for record in records
            if event.date <= record.attendance_date <= event.last_attendance_date
        )
        status = "ABSENT"
        if completed_days == event.attendance_day_count:
            status = "EXCUSED" if event.attendance_day_count == 1 and attendance.excused_time_out else "ATTENDED"
        elif any(record.in_at for record in records):
            status = "INCOMPLETE" if event.attendance_day_count > 1 else "IN ONLY"

        event_history.append({
            "event": event,
            "attendance": attendance,
            "status": status,
            "daily_records": records,
            "completed_days": completed_days,
        })

    return event_history


@login_required
def student_dashboard(request, section="overview"):
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role != Profile.Role.STUDENT:
        raise PermissionDenied

    now = timezone.now()
    Event.refresh_statuses(now=now)
    context = {"profile": profile, "student_section": section}
    if section == "overview":
        context["upcoming_events"] = (
            Event.objects.filter(status__in=(Event.Status.UPCOMING, Event.Status.ONGOING))
            .order_by("date", "start_time", "pk")[:3]
        )
        time_ins = Attendance.checked_in_records(profile, now)
        context["current_time_ins"] = time_ins
        context["checked_in_event_ids"] = {record.event_id for record in time_ins}
    elif section == "qr":
        context["checked_in_event_ids"] = Attendance.checked_in_event_ids(profile, now)
        ongoing_events = Event.objects.filter(status=Event.Status.ONGOING).order_by("date", "start_time", "pk")
        # A program can be ongoing between its daily sessions. Show the one currently in session.
        for active_event in ongoing_events:
            day = active_event.attendance_date_at(now)
            session = active_event.attendance_session(day)
            if session.starts_at <= now < session.ends_at:
                context.update(
                    active_event=active_event,
                    active_day=day,
                    active_day_number=(day - active_event.date).days + 1,
                )
                break

    if section in ("overview", "stamps"):
        context.update(_stamp_card(profile))
    if section in ("overview", "stamps", "history"):
        context["event_history"] = _event_history(profile)
    return render(request, "stamps/student_dashboard.html", context)


# Refresh the signed-in student's check-ins and badges without reloading the page.
@login_required
@never_cache
@require_GET
def student_attendance_status(request):
    if account_role(request.user) != Profile.Role.STUDENT:
        raise PermissionDenied
    time_ins = Attendance.checked_in_records(request.user.profile, timezone.now())
    updates = {"in_event_ids": sorted({record.event_id for record in time_ins})}
    if request.GET.get("include_time_ins") == "1":
        updates["current_time_ins"] = render_to_string(
            "stamps/partials/current_time_ins.html", {"current_time_ins": time_ins},
        )
    return JsonResponse(updates)


# Generate a fresh PNG of the signed QR token for the current student.
@login_required
def student_qr(request):
    profile = getattr(request.user, "profile", None)

    if not profile or profile.role != Profile.Role.STUDENT:
        return HttpResponse("Student access required.", status=403)

    token = create_qr_token(profile)

    # Configure the QR's size, border, and error correction before adding the token.
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(token)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    # Encode the image in memory for the HTTP response.
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    response = HttpResponse(buffer.getvalue(), content_type="image/png")
    # Tell the dashboard when to refresh and mark the response as unsuitable for caching.
    expires_at = qr_token_expiry(token)
    response["X-QR-Expires-At"] = str(expires_at)
    response["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, "
        "proxy-revalidate, max-age=0"
    )
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"

    return response
