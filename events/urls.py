# Named routes for event browsing, the organizer dashboard, and event forms.
from django.urls import path
from . import views


app_name = "events"


urlpatterns = [
    path("", views.event_list, name="event_list"),
    # This older analytics path now redirects to the dashboard's analytics section.
    path("analytics/", views.attendance_analytics, name="analytics"),

    path(
        "organizer/",
        views.organizer_dashboard,
        name="organizer_dashboard"
    ),
    path(
        "organizer/events/",
        views.organizer_dashboard,
        {"section": "events"},
        name="organizer_events",
    ),

    path(
        "create/",
        views.event_create,
        name="event_create"
    ),

    path(
        # Django passes pk as the numeric ID of the event to display.
        "<int:pk>/",
        views.event_detail,
        name="event_detail"
    ),

    path(
        "<int:pk>/edit/",
        views.event_edit,
        name="event_edit"
    ),
]
