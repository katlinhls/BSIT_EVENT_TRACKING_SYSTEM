# Named routes for signing in, registering, editing a profile, and changing or resetting a
# password.
from django.urls import path
from . import views

# The namespace groups route names so templates can link to the correct app.
app_name = "accounts"

# The path string is the URL after the accounts prefix. The view handles the request.
urlpatterns = [
    path("student-login/", views.student_login, name="student_login"),
    path("organizer-login/", views.organizer_login, name="organizer_login"),
    path("register/", views.register_student, name="register_student"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("password/required/", views.required_password, name="required_password"),
    path("organizer/change-password/", views.required_password, name="organizer_password_change"),
    path("password/change/", views.AccountPasswordChangeView.as_view(), name="password_change"),
    path("notifications/", views.notifications, name="notifications"),

    path(
        # Open the form that asks for the account email.
        "password-reset/",
        views.AccountPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        views.AccountPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        # Take the encoded user ID and reset token from the link sent by email.
        "password-reset/<uidb64>/<token>/",
        views.AccountPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        views.AccountPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
