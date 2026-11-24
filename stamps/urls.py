# Routes for the student dashboard and its signed QR image.
from django.urls import path
from . import views

app_name = "stamps"

urlpatterns = [
    path(
        # Open the student's overview with stamps and attendance history.
        "students/",
        views.student_dashboard,
        name="student_dashboard"
    ),
    path("students/my-qr/", views.student_dashboard, {"section": "qr"}, name="student_qr_page"),
    path("students/stamps/", views.student_dashboard, {"section": "stamps"}, name="student_stamps_page"),
    path("students/history/", views.student_dashboard, {"section": "history"}, name="student_history_page"),
    path("students/attendance-status/", views.student_attendance_status, name="student_attendance_status"),

    path(
        # Return the rotating QR image requested by the dashboard script.
        "student/qr/",
        views.student_qr,
        name="student_qr"
    ),
]
