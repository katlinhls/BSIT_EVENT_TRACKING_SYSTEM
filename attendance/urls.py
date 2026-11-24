# Event-scoped routes for the camera scanner, scan submissions, attendance lists, and
# downloads.
from django.urls import path
from . import views

app_name = "attendance"

# Django passes event_id from the URL to each attendance view.
urlpatterns = [
    path("event/<int:event_id>/scanner/", views.scanner, name="scanner"),
    path("event/<int:event_id>/timing/", views.scanner_timing, name="scanner_timing"),
    # The scanner sends its POST requests to this JSON endpoint.
    path("event/<int:event_id>/scan/", views.scan_api, name="scan_api"),
    path("event/<int:event_id>/list/", views.attendance_list, name="attendance_list"),
    path("event/<int:event_id>/export/", views.attendance_export, name="attendance_export"),
]
