# Handle event lists, event forms, and the organizer dashboard.
from collections import Counter
from math import ceil

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.access import account_role, dashboard_name, is_portal_admin
from accounts.models import Profile
from accounts.views import required_password
from administration.audit import record_activity
from administration.models import ActivityLog
from attendance.models import Attendance

from .analytics import attendance_summary
from .forms import EventForm
from .models import Event
from .reminders import remind_event_ending, schedule_refresh_delay


# Group unfinished checkouts by their original attendance day, even during a later session.
def _pending_checkouts(events, now):
    by_id = {event.pk: event for event in events if event.status != Event.Status.CANCELLED}
    pending = (
        Attendance.awaiting_time_out(now).filter(event_id__in=by_id)
        .values("event_id", "attendance_date")
        .annotate(student_count=Count("pk"))
        .order_by("-attendance_date", "event_id")
    )
    rows = []
    for record in pending:
        event = by_id[record["event_id"]]
        day = record["attendance_date"]
        if event.date <= day <= event.last_attendance_date and event.attendance_session(day).ends_at <= now:
            rows.append({"event": event, "day": day, "student_count": record["student_count"]})
    return rows


# Show the signed-in organizer's overview or the full list of assigned events.
@login_required
@never_cache
def organizer_dashboard(request, section="overview"):
    if account_role(request.user) != Profile.Role.ORGANIZER:
        raise PermissionDenied
    if request.user.profile.must_change_password:
        return required_password(request)
    now = timezone.now()
    Event.refresh_statuses(now=now)
    # Scope the event table, pending checkouts, and analytics to the signed-in organizer.
    owned_events = Event.objects.filter(organizer=request.user).order_by("-date", "-start_time", "pk")
    status_order = {status: index for index, status in enumerate((
        Event.Status.ONGOING, Event.Status.UPCOMING, Event.Status.COMPLETED, Event.Status.CANCELLED,
    ))}
    events = sorted(owned_events, key=lambda event: status_order.get(event.status, len(status_order)))
    context = {
        "organizer_section": section,
        "refresh_after_ms": schedule_refresh_delay(events, now),
    }
    if section == "events":
        context.update(events=events, pending_checkouts=_pending_checkouts(events, now))
        return render(request, "events/organizer_events.html", context)

    ending_notices = [
        {"event": event, "minutes": ceil((event.ends_at - now).total_seconds() / 60)}
        for event in events if remind_event_ending(event, now)
    ]
    counts = Counter(event.status for event in events)
    metrics = [
        ("Events", len(events), "organizer", "blue"),
        ("Ongoing", counts[Event.Status.ONGOING], "clock", "mint"),
        ("Upcoming", counts[Event.Status.UPCOMING], "activity", "violet"),
        ("Completed", counts[Event.Status.COMPLETED], "check", "blue"),
    ]
    context.update({
        "events": events[:3],
        "has_more_events": len(events) > 3,
        "ending_notices": ending_notices,
        "today": timezone.localdate(now),
        "metrics": metrics,
        "analytics": attendance_summary(owned_events, request.GET, group_by_program=True),
    })
    return render(request, "events/organizer_dashboard.html", context)


# Redirect earlier analytics links to the matching dashboard section with the selected filter.
@login_required
@never_cache
def attendance_analytics(request):
    if account_role(request.user) not in (Profile.Role.ADMIN, Profile.Role.ORGANIZER):
        raise PermissionDenied

    return redirect(reverse(dashboard_name(request.user), query=request.GET, fragment="analytics"))


# Show the general event list and send administrators to their management list.
@login_required
def event_list(request):
    if is_portal_admin(request.user):
        return redirect("administration:events")
    Event.refresh_statuses()
    return render(request, "events/event_list.html", {
        "events": Event.objects.all(), "student_section": "overview", "organizer_section": "events",
    })


# Show the selected event and decide whether the organizer can manage it.
@login_required
def event_detail(request, pk):
    if is_portal_admin(request.user):
        return redirect("administration:event_detail", pk=pk)
    event = get_object_or_404(Event.objects.select_related("organizer"), pk=pk)
    now = timezone.now()
    event.sync_status(now=now)
    role = account_role(request.user)
    if role == Profile.Role.STUDENT:
        return render(request, "stamps/event_detail.html", {
            "event": event,
            "student_section": "history" if event.status == Event.Status.COMPLETED else "overview",
            "checked_in_event_ids": Attendance.checked_in_event_ids(request.user.profile, now),
        })

    can_manage_event = (
        role == Profile.Role.ORGANIZER
        and event.organizer_id == request.user.pk
    )
    can_finish_time_out = (
        can_manage_event and event.status == Event.Status.COMPLETED
        and Attendance.awaiting_time_out(now).filter(event=event).exists()
    )
    return render(request, "events/event_detail.html", {
        "event": event,
        "organizer_section": "events",
        "can_manage_event": can_manage_event,
        "can_finish_time_out": can_finish_time_out,
    })


# Share validation and saving between event creation and editing for both roles.
def _event_form(request, event=None):
    administrator = is_portal_admin(request.user)
    submitted = request.method == "POST"
    form = EventForm(
        request.POST if submitted else None,
        request.FILES if submitted else None,
        instance=event,
        user=request.user,
        label_suffix="",
    )
    detail_name = "administration:event_detail" if administrator else "events:event_detail"
    if submitted and form.is_valid():
        # Build the event first so ownership and status can be set before the database write.
        saved_event = form.save(commit=False)
        if not administrator:
            saved_event.organizer = request.user
        # Require a fresh approval after a schedule, assignment, or status change.
        if {"date", "end_date", "start_time", "end_time", "organizer", "status"}.intersection(form.changed_data):
            saved_event.early_time_out_until = None
        saved_event.sync_status(save=False)
        saved_event.save()
        # Log an event creation or a saved edit that changed the form values.
        if event is None or form.has_changed():
            action = ActivityLog.Action.EVENT_CREATED if event is None else ActivityLog.Action.EVENT_UPDATED
            record_activity(request.user, action, saved_event.name, f"Event #{saved_event.pk}")
        messages.success(request, "Event created." if event is None else "Event updated.")
        return redirect(detail_name, pk=saved_event.pk)

    cancel_name = (
        detail_name if event else
        "administration:events" if administrator else "events:organizer_dashboard"
    )
    context = {
        "form_base_template": "administration/base.html" if administrator else "events/organizer_base.html",
        "section": "events",
        "title": "Edit event" if event else "Create event",
        "form": form,
        "cancel_name": cancel_name,
        "cancel_pk": event.pk if event else None,
        "submit_label": "Save event" if event else "Create event",
        "organizer_section": "events" if event else "create",
    }
    return render(request, "events/event_form.html", context)


# Allow an administrator or organizer to open the new-event form.
@login_required
@transaction.atomic
def event_create(request):
    if account_role(request.user) not in (Profile.Role.ADMIN, Profile.Role.ORGANIZER):
        raise PermissionDenied
    return _event_form(request)


# Check the role and ownership before allowing changes to an existing event.
@login_required
@transaction.atomic
def event_edit(request, pk):
    role = account_role(request.user)
    if role not in (Profile.Role.ADMIN, Profile.Role.ORGANIZER):
        raise PermissionDenied
    # Request a row lock when a POST is editing a saved event.
    events = Event.objects.select_for_update() if request.method == "POST" else Event.objects.all()
    event = get_object_or_404(events, pk=pk)
    if role == Profile.Role.ORGANIZER and event.organizer_id != request.user.pk:
        raise PermissionDenied
    if event.is_completed:
        messages.info(request, "Completed events are view-only.")
        detail_name = "administration:event_detail" if role == Profile.Role.ADMIN else "events:event_detail"
        return redirect(detail_name, pk=event.pk)
    return _event_form(request, event)
