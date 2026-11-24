# Serve the organizer's scanner, process time-in and time-out requests, and export attendance.
from io import BytesIO
from math import ceil

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers

from accounts.access import account_role, is_portal_admin
from accounts.models import Profile
from administration.audit import record_activity
from administration.models import ActivityLog
from events.models import Event
from events.reminders import remind_event_ending
from .live import live_attendance_response
from .models import Attendance
from .reporting import event_attendance_records, parse_attendance_day
from .services import sync_attendance_stamp, validate_qr_token

SCANNER_REFRESH_MS = 1000

# Require the organizer role and a match with the event's assigned organizer.
def _owns_event(user, event):
    return account_role(user) == Profile.Role.ORGANIZER and event.organizer_id == user.pk


def _schedule_label(moment):
    return date_format(timezone.localtime(moment), "M j, g:i a")


def _time_out_message(event, session, state):
    if state == Event.TimeOut.CLOSED:
        return f"Scanning is closed for this {event.get_status_display().lower()} event."
    if state == Event.TimeOut.FUTURE_DAY:
        return "This attendance day has not started."
    if state == Event.TimeOut.AFTER_END:
        return "Time In has closed for this day. Students who timed in can still time out."
    if state == Event.TimeOut.OPEN:
        return "Time Out is open. Students who timed in can still check out after the session ends."
    if state == Event.TimeOut.APPROVED:
        return f"Early Time Out is approved until {_schedule_label(event.early_time_out_until)}."
    opening = f"Time Out opens {_schedule_label(session.time_out_opens_at)}."
    if state == Event.TimeOut.LOCKED:
        return f"{opening} Ask an administrator to approve early Time Out from the event's admin page."
    return opening


# Return the current scanner controls and schedule the next status check.
def _scanner_timing(event, session, now):
    state = event.time_out_state(now, session)
    scanning_open = state not in {Event.TimeOut.CLOSED, Event.TimeOut.FUTURE_DAY}
    message = _time_out_message(event, session, state)
    if state == Event.TimeOut.AFTER_END:
        pending = Attendance.awaiting_time_out(now).filter(event=event, attendance_date=session.day).count()
        scanning_open = pending > 0
        message = (
            f"Time Out only · {pending} remaining."
            if scanning_open else "No students are waiting to time out for this day."
        )

    transitions = (
        session.starts_at, session.time_out_opens_at, session.ends_at,
        event.ends_at, event.early_time_out_until,
    )
    delay = min(
        (ceil((moment - now).total_seconds() * 1000) for moment in transitions if moment and moment > now),
        default=SCANNER_REFRESH_MS,
    )
    return {
        "scanning_open": scanning_open,
        "day": session.day.isoformat(),
        "time_in_allowed": state.allows_time_in,
        "time_out_allowed": scanning_open and state.allows_time_out,
        "excused_time_out_allowed": state.allows_excused_time_out,
        "message": message,
        "show_end_reminder": remind_event_ending(event, now),
        "end_label": _schedule_label(event.ends_at),
        "refresh_after_ms": max(100, min(delay, SCANNER_REFRESH_MS)),
    }


def _scanner_session(request, event, now, *, find_pending=False):
    try:
        day = parse_attendance_day(event, request.GET.get("day"))
    except ValueError as error:
        raise Http404("Choose a day within the event schedule.") from error
    if day is None and find_pending and event.time_out_state(now) == Event.TimeOut.AFTER_END:
        # Opening the scanner after the session ends should find an unfinished day.
        day = (
            Attendance.awaiting_time_out(now).filter(event=event, attendance_date__range=event.attendance_date_range)
            .order_by("-attendance_date").values_list("attendance_date", flat=True).first()
        )
    return event.attendance_session(day or event.attendance_date_at(now))


# Display the camera scanner for the organizer assigned to this event.
@login_required
@require_GET
def scanner(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if not _owns_event(request.user, event):
        raise PermissionDenied
    now = timezone.now()
    event.sync_status(now=now)
    session = _scanner_session(request, event, now, find_pending=True)
    timing = _scanner_timing(event, session, now)
    if not timing["scanning_open"]:
        messages.info(request, timing["message"])
        query = {"day": session.day.isoformat()} if event.attendance_day_count > 1 else None
        return redirect(reverse("attendance:attendance_list", args=[event.pk], query=query))
    return render(request, "attendance/scanner.html", {
        "event": event, "session": session, "timing": timing, "organizer_section": "events",
    })


# Let an open scanner pick up the end time and administrator approval without reloading.
@login_required
@require_GET
def scanner_timing(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if not _owns_event(request.user, event):
        raise PermissionDenied
    now = timezone.now()
    event.sync_status(now=now)
    return JsonResponse(_scanner_timing(event, _scanner_session(request, event, now), now))


# Receive a scanned QR and return a JSON result that the scanner page can display.
@login_required
@transaction.atomic
def scan_api(request, event_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST required."}, status=405)

    # Hold the event while checking its schedule and writing the attendance record.
    event = get_object_or_404(Event.objects.select_for_update(), pk=event_id)
    if not _owns_event(request.user, event):
        return JsonResponse({"ok": False, "message": "You are not assigned to this event."}, status=403)
    now = timezone.now()
    event.sync_status(now=now)
    try:
        day = parse_attendance_day(event, request.POST.get("day"))
    except ValueError:
        return JsonResponse({"ok": False, "message": "Choose a day within the event schedule."}, status=400)
    session = event.attendance_session(day or event.attendance_date_at(now))
    time_out_state = event.time_out_state(now, session)
    if time_out_state in {Event.TimeOut.CLOSED, Event.TimeOut.FUTURE_DAY}:
        return JsonResponse({"ok": False, "message": _time_out_message(event, session, time_out_state)}, status=409)

    # Read the QR text and the mode selected on the scanner page.
    token = request.POST.get("token", "").strip()
    scan_type = request.POST.get("scan_type", "").upper()

    if scan_type not in {"IN", "OUT", "EXCUSED_OUT"}:
        return JsonResponse({"ok": False, "message": "Invalid scan type."}, status=400)
    if scan_type == "IN" and not time_out_state.allows_time_in:
        return JsonResponse({"ok": False, "message": _time_out_message(event, session, time_out_state)}, status=409)
    if scan_type == "OUT" and not time_out_state.allows_time_out:
        return JsonResponse({"ok": False, "message": _time_out_message(event, session, time_out_state)}, status=403)
    excused = scan_type == "EXCUSED_OUT"
    if excused and not time_out_state.allows_excused_time_out:
        return JsonResponse({
            "ok": False, "message": "Excused Time Out is available during the scheduled session.",
        }, status=409)

    payload, error = validate_qr_token(token)
    if error:
        return JsonResponse({"ok": False, "message": error}, status=400)

    # Use the verified user ID to look up an active student whose password setup is complete.
    profile = Profile.objects.filter(
        user_id=payload.get("uid"), role=Profile.Role.STUDENT,
        user__is_active=True, must_change_password=False,
    ).select_related("user").first()
    if not profile:
        return JsonResponse({"ok": False, "message": "Student account not found."}, status=404)

    try:
        # Record the scan and any stamp or activity entry as a single database operation.
        with transaction.atomic():
            attendance = (
                Attendance.objects
                .select_for_update()
                .filter(student=profile, event=event, attendance_date=session.day)
                .first()
            )

            subject = f"{event.name} · {session.day:%Y-%m-%d} · {profile.display_name} ({profile.student_id or profile.user.username})"
            # Use the time-in path to create the row if needed and reject repeated time-ins.
            if scan_type == "IN":
                if attendance and attendance.in_at:
                    return JsonResponse({
                        "ok": False,
                        "message": f"{profile.display_name} already has an IN scan for this day.",
                        "student": profile.display_name,
                        "already_recorded": True,
                    }, status=409)

                if attendance is None:
                    attendance = Attendance(student=profile, event=event, attendance_date=session.day)

                attendance.in_at = now
                attendance.in_scanned_by = request.user
                attendance.save()
                record_activity(request.user, ActivityLog.Action.CHECK_IN, subject)

                return JsonResponse({
                    "ok": True,
                    "message": f"IN recorded for {profile.display_name}.",
                    "student": profile.display_name,
                    "student_id": profile.student_id,
                    "scan_type": "IN",
                    "time": timezone.localtime(now).strftime("%I:%M:%S %p"),
                })

            # OUT
            # Time out requires a valid time in for the selected day.
            if attendance is None or not attendance.in_at or now < attendance.in_at:
                return JsonResponse({
                    "ok": False,
                    "message": f"{profile.display_name} has no valid IN scan for this day.",
                    "student": profile.display_name,
                }, status=409)

            if attendance.out_at:
                return JsonResponse({
                    "ok": False,
                    "message": f"{profile.display_name} already has an OUT scan for this day.",
                    "student": profile.display_name,
                    "already_recorded": True,
                }, status=409)

            attendance.out_at = now
            attendance.out_scanned_by = request.user
            attendance.excused_time_out = excused
            attendance.save()

            # Save the event's award in the same transaction as the checkout.
            stamp_quantity = sync_attendance_stamp(attendance)
            if excused:
                details = "Excused Time Out recorded during the event."
            elif time_out_state == Event.TimeOut.APPROVED:
                details = "Early Time Out approved by an administrator."
            elif time_out_state == Event.TimeOut.AFTER_END:
                details = "Time Out recorded after the attendance session ended."
            else:
                details = ""
            record_activity(request.user, ActivityLog.Action.CHECK_OUT, subject, details)

            label = "Excused Time Out" if excused else "Time Out"
            message = f"{label} recorded for {profile.display_name}."
            if stamp_quantity:
                noun = "stamp" if stamp_quantity == 1 else "stamps"
                message += f" {stamp_quantity} {noun} awarded."
            response = {
                "ok": True,
                "message": message,
                "student": profile.display_name,
                "student_id": profile.student_id,
                "scan_type": scan_type,
                "time": timezone.localtime(now).strftime("%I:%M:%S %p"),
                "stamp_awarded": bool(stamp_quantity),
                "stamps_awarded": stamp_quantity,
            }
            if time_out_state == Event.TimeOut.AFTER_END:
                response["timing"] = _scanner_timing(event, session, now)
            return JsonResponse(response)

    # The database's unique rule handles attempts to create the same attendance row at once.
    except IntegrityError:
        return JsonResponse({"ok": False, "message": "Attendance already exists."}, status=409)

# Show the event's attendance to its organizer and route administrators to their management
# view.
@login_required
@vary_on_headers("Accept")
def attendance_list(request, event_id):
    if is_portal_admin(request.user):
        return redirect("administration:attendance_records", event_id=event_id)
    event = get_object_or_404(Event, pk=event_id)
    if not _owns_event(request.user, event):
        raise PermissionDenied

    now = timezone.now()
    event.sync_status(now=now)
    try:
        day = parse_attendance_day(event, request.GET.get("day"))
    except ValueError as error:
        raise Http404("Choose a day within the event schedule.") from error
    records = event_attendance_records(event)
    pending = Attendance.awaiting_time_out(now).filter(event=event)
    session = event.attendance_session(day or event.attendance_date_at(now))
    state = event.time_out_state(now, session)
    if day:
        records = records.filter(attendance_date=day)
        pending = pending.filter(attendance_date=day)
    can_finish_time_out = state == Event.TimeOut.AFTER_END and pending.exists()
    selected_scanner_day = day if can_finish_time_out or state.allows_time_in else None
    context = {
        "event": event, "records": records, "can_finish_time_out": can_finish_time_out,
        "selected_day": day, "scanner_day": selected_scanner_day, "organizer_section": "events",
    }
    if request.method == "GET" and request.headers.get("Accept") == "application/json":
        return live_attendance_response(request, context, {
            "rows": "attendance/partials/record_rows.html",
            "actions": "attendance/partials/list_actions.html",
        })
    return render(request, "attendance/attendance_list.html", context)


# Build an Excel workbook for an administrator or the event's assigned organizer.
@login_required
@require_GET
def attendance_export(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if not (is_portal_admin(request.user) or _owns_event(request.user, event)):
        raise PermissionDenied

    # Stream rows into the workbook and keep the header visible while scrolling.
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Attendance")
    sheet.freeze_panes = "A2"
    daily = event.attendance_day_count > 1
    for column, width in (("A", 22), ("B", 34), ("C", 26), ("D", 26), ("E", 17), ("F", 18), ("G", 18)):
        sheet.column_dimensions[column].width = width
    zone = timezone.get_current_timezone_name()
    headers = ["School ID", "Student", f"Time in ({zone})", f"Time out ({zone})", "Status"]
    if daily:
        headers.extend(["Attendance day", "Days completed"])
    sheet.append(headers)

    # Write school IDs and names as literal text so Excel preserves their values.
    def text_cell(value):
        cell = WriteOnlyCell(sheet, value=value)
        cell.data_type = "s"
        return cell

    # Convert stored times to local clock values for Excel and leave missing times blank.
    def local_time(value):
        if value:
            cell = WriteOnlyCell(sheet, value=timezone.localtime(value).replace(tzinfo=None))
            cell.number_format = "yyyy-mm-dd hh:mm:ss"
            return cell
        return None

    records = event_attendance_records(event).order_by("student__student_id", "attendance_date", "pk")
    for record in records.iterator():
        row = [
            text_cell(record.student.student_id or record.student.user.username),
            text_cell(record.student.display_name),
            local_time(record.in_at),
            local_time(record.out_at),
            record.status.title(),
        ]
        if daily:
            row.extend([record.attendance_date, f"{record.days_completed} of {event.attendance_day_count}"])
        sheet.append(row)

    # Save the workbook into memory and return it as a downloadable file.
    result = BytesIO()
    workbook.save(result)
    response = HttpResponse(
        result.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="attendance-event-{event.pk}.xlsx"'
    response["Cache-Control"] = "private, no-store"
    return response
