# URL names for the custom administrator portal.
from django.urls import path

from events import views as event_views

from . import attendance, users, views
from accounts.access import administrator_required

app_name = "administration"

# Each entry pairs a route with the view that handles it.
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.admin_login, name="login"),
    # Account routes use the user's numeric ID for actions on a single account.
    path("accounts/", users.account_list, name="accounts"),
    path("accounts/create/", users.account_create, name="account_create"),
    path("accounts/<int:pk>/", users.account_detail, name="account_detail"),
    path("accounts/<int:pk>/status/", users.account_status, name="account_status"),
    path("accounts/<int:pk>/delete/", users.account_delete, name="account_delete"),
    path("accounts/<int:pk>/password/", users.account_password, name="account_password"),
    path("accounts/<int:pk>/reset-email/", users.account_reset_email, name="account_reset_email"),
    # Event creation and editing reuse the event views with an administrator check.
    path("events/", views.event_list, name="events"),
    path("events/create/", administrator_required(event_views.event_create), name="event_create"),
    path("events/<int:pk>/", views.event_detail, name="event_detail"),
    path("events/<int:pk>/edit/", administrator_required(event_views.event_edit), name="event_edit"),
    path("events/<int:pk>/early-time-out/", views.approve_early_time_out, name="approve_early_time_out"),
    path("events/<int:pk>/delete/", views.event_delete, name="event_delete"),
    # These routes lead to attendance lists and manual corrections.
    path("attendance/", attendance.event_index, name="attendance"),
    # Keep existing analytics links working by redirecting them to the overview section.
    path("analytics/", administrator_required(event_views.attendance_analytics), name="analytics"),
    path("attendance/<int:event_id>/", attendance.event_records, name="attendance_records"),
    path("attendance/<int:event_id>/add/", attendance.correct, name="attendance_add"),
    path("attendance/<int:event_id>/<int:record_id>/correct/", attendance.correct, name="attendance_correct"),
    path("activity/", views.activity, name="activity"),
]
