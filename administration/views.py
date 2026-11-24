# Render the administrator overview, event management pages, and activity log.
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from accounts.access import administrator_required, is_portal_admin
from accounts.models import Profile
from attendance.models import Attendance
from events.analytics import attendance_summary
from events.models import Event

from .audit import record_activity
from .forms import AdministratorLoginForm, EarlyTimeOutApprovalForm
from .models import ActivityLog


# Use the management login form and send authenticated administrators to Overview.
@never_cache
def admin_login(request):
    if request.user.is_authenticated:
        if not is_portal_admin(request.user):
            raise PermissionDenied
        return redirect("administration:dashboard")
    form = AdministratorLoginForm(request, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("administration:dashboard")
    return render(request, "administration/login.html", {"form": form})


# Count time-ins and time-outs for each of the last seven calendar days.
def _attendance_week(today):
    start = today - timedelta(days=6)
    days = [start + timedelta(days=offset) for offset in range(7)]
    totals = {}
    for field in ("in_at", "out_at"):
        rows = (
            Attendance.objects.filter(**{f"{field}__date__range": (start, today)})
            .annotate(day=TruncDate(field)).values("day").annotate(total=Count("pk"))
        )
        # Store daily counts by date so a day with no scans can show zero.
        totals[field] = {row["day"]: row["total"] for row in rows}

    # Scale both series to the same largest count so the bar heights can be compared.
    peak = max((count for counts in totals.values() for count in counts.values()), default=0)
    return [
        {
            "day": day,
            "check_ins": totals["in_at"].get(day, 0),
            "check_outs": totals["out_at"].get(day, 0),
            "in_height": round(totals["in_at"].get(day, 0) * 100 / max(peak, 1)),
            "out_height": round(totals["out_at"].get(day, 0) * 100 / max(peak, 1)),
        }
        for day in days
    ]


# Gather the cards, charts, recent events, and recent activity shown on Admin Overview.
@administrator_required
def dashboard(request):
    Event.refresh_statuses()
    today = timezone.localdate()
    # Count active student and organizer accounts for the top overview cards.
    accounts = dict(
        Profile.objects.filter(user__is_active=True, user__is_staff=False, user__is_superuser=False)
        .values_list("role")
        .annotate(total=Count("pk"))
    )
    event_counts = dict(Event.objects.values_list("status").annotate(total=Count("pk")))
    total_events = sum(event_counts.values())
    statuses = [
        {
            "code": status.value,
            "label": status.label,
            "count": event_counts.get(status.value, 0),
            "percent": round(event_counts.get(status.value, 0) * 100 / max(total_events, 1)),
        }
        for status in Event.Status
    ]
    metrics = [
        {"label": "Active students", "value": accounts.get(Profile.Role.STUDENT, 0), "icon": "student", "page": "administration:accounts", "query": "?role=STUDENT&status=active"},
        {"label": "Active organizers", "value": accounts.get(Profile.Role.ORGANIZER, 0), "icon": "users", "page": "administration:accounts", "query": "?role=ORGANIZER&status=active"},
        {"label": "Total events", "value": total_events, "icon": "organizer", "page": "administration:events"},
        {"label": "Completed attendance", "value": Attendance.objects.filter(in_at__isnull=False, out_at__isnull=False).count(), "icon": "check", "page": "administration:attendance"},
    ]
    return render(request, "administration/dashboard.html", {
        "section": "overview",
        "today": today,
        "metrics": metrics,
        # The administrator overview gives the shared analytics helper access to all events.
        "analytics": attendance_summary(Event.objects.all(), request.GET),
        "week": _attendance_week(today),
        "statuses": statuses,
        "events": Event.objects.select_related("organizer").order_by("-created_at", "-pk")[:5],
        "activity": ActivityLog.objects.all()[:4],
    })


# Apply a search and event-status filter before paging the full event list.
@administrator_required
def event_list(request):
    Event.refresh_statuses()
    events = Event.objects.select_related("organizer").order_by("-date", "-start_time", "-pk")
    term = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if term:
        events = events.filter(Q(name__icontains=term) | Q(venue__icontains=term))
    if status in Event.Status.values:
        events = events.filter(status=status)
    return render(request, "administration/events.html", {
        "section": "events",
        "page_obj": Paginator(events, 20).get_page(request.GET.get("page")),
        "search_term": term,
        "status_filter": status,
        "statuses": Event.Status.choices,
    })


# Show one event and count how many attendees have timed in or completed both scans.
@administrator_required
def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related("organizer"), pk=pk)
    now = timezone.now()
    event.sync_status(now=now)
    totals = event.attendance_records.aggregate(
        checked_in=Count("pk", filter=Q(in_at__isnull=False)),
        completed=Count("pk", filter=Q(in_at__isnull=False, out_at__isnull=False)),
    )
    return render(request, "administration/event_detail.html", {
        "section": "events", "event": event, "totals": totals,
        "can_approve_early_time_out": event.organizer_id and event.time_out_state(now) == Event.TimeOut.LOCKED,
    })


# Approve a short early Time Out window in the administrator's own session.
@sensitive_post_parameters("password")
@administrator_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def approve_early_time_out(request, pk):
    submitted = request.method == "POST"
    events = Event.objects.select_for_update() if submitted else Event.objects.all()
    event = get_object_or_404(events, pk=pk)
    now = timezone.now()
    if not event.organizer_id or event.time_out_state(now) != Event.TimeOut.LOCKED:
        messages.info(request, "Early Time Out approval is only available while Time Out is locked for an ongoing event.")
        return redirect("administration:event_detail", pk=pk)

    form = EarlyTimeOutApprovalForm(request.POST if submitted else None, user=request.user)
    if submitted and form.is_valid():
        # Recheck after password verification in case the ordinary window has opened.
        now = timezone.now()
        if event.time_out_state(now) == Event.TimeOut.LOCKED:
            session = event.attendance_session(event.attendance_date_at(now))
            event.early_time_out_until = min(now + timedelta(minutes=5), session.time_out_opens_at)
            event.save(update_fields=["early_time_out_until"])
            record_activity(
                request.user, ActivityLog.Action.EARLY_TIME_OUT_APPROVED, event.name,
                f"Event #{event.pk} · Approved until {timezone.localtime(event.early_time_out_until):%Y-%m-%d %H:%M:%S}.",
            )
            messages.success(request, "Early Time Out is approved. The organizer's scanner will unlock automatically.")
        else:
            messages.info(request, "The Time Out schedule changed while you were approving it.")
        return redirect("administration:event_detail", pk=pk)

    return render(request, "administration/approve_early_time_out.html", {
        "section": "events", "event": event, "form": form,
    })


# Show a confirmation on GET and delete the selected event after a POST.
@administrator_required
@transaction.atomic
def event_delete(request, pk):
    events = Event.objects.select_for_update() if request.method == "POST" else Event.objects.all()
    event = get_object_or_404(events, pk=pk)
    if event.is_completed:
        messages.info(request, "Completed events are view-only.")
        return redirect("administration:event_detail", pk=event.pk)
    if request.method == "POST":
        record_activity(
            request.user, ActivityLog.Action.EVENT_DELETED, event.name,
            f"Event #{pk}, scheduled for {event.date}.",
        )
        # Delete after the activity entry captures the event's name and date.
        event.delete()
        messages.success(request, "Event deleted.")
        return redirect("administration:events")

    return render(request, "administration/event_delete.html", {
        "section": "events", "event": event,
        "attendance_count": event.attendance_records.count(),
        "stamp_count": event.stamps.aggregate(total=Sum("quantity", default=0))["total"],
    })


# Search and page activity entries, with an optional filter for the action type.
@administrator_required
def activity(request):
    logs = ActivityLog.objects.all()
    term = request.GET.get("q", "").strip()
    action = request.GET.get("action", "")
    if term:
        logs = logs.filter(
            Q(actor_username__icontains=term) | Q(subject__icontains=term)
            | Q(details__icontains=term)
        )
    if action in ActivityLog.Action.values:
        logs = logs.filter(action=action)
    return render(request, "administration/activity.html", {
        "section": "activity",
        "page_obj": Paginator(logs, 25).get_page(request.GET.get("page")),
        "search_term": term,
        "action_filter": action,
        "actions": ActivityLog.Action.choices,
    })
