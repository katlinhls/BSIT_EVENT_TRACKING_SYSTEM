# Top-level URL map. Each included app handles the routes for its own feature.
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path
from django.utils.crypto import salted_hmac


# Render the landing page with the sign-in options.
def home(request):
    return render(request, "home.html")


# Generate a stable address for the custom admin portal from the Django signing key.
admin_portal_path = salted_hmac(
    "bsit-events.admin-portal-path", "portal", algorithm="sha256"
).hexdigest()[:32]


# Connect the main URL prefixes to Django admin and the project apps.
urlpatterns = [
    path("admin/", admin.site.urls),
    path(f"{admin_portal_path}/", include("administration.urls")),

    path("", home, name="home"),

    path("accounts/", include("accounts.urls")),
    path("events/", include("events.urls")),
    path("attendance/", include("attendance.urls")),
    path("", include("stamps.urls")),
]


# Serve uploaded media through Django during local development.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
