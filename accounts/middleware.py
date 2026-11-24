# Protect account routes and keep the administrator address out of debug 404 pages.
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect
from django.utils.cache import add_never_cache_headers
from django.views.defaults import page_not_found

from .access import account_role
from .models import Profile


def prevent_account_page_cache(get_response):
    """Keep signed-in responses and the logout redirect out of the HTTP cache."""
    def middleware(request):
        was_signed_in = request.user.is_authenticated
        response = get_response(request)
        if was_signed_in or request.user.is_authenticated:
            add_never_cache_headers(response)
        return response

    return middleware


def hide_debug_404_routes(get_response):
    """Replace debug HTML 404 pages that can display URL patterns."""
    def middleware(request):
        response = get_response(request)
        if (
            settings.DEBUG
            and response.status_code == 404
            and response.headers.get("Content-Type", "").startswith("text/html")
        ):
            return page_not_found(request, Http404())
        return response

    return middleware


class RequirePasswordChangeMiddleware:
    """Keep temporary-password sessions out of the application until updated."""

    # Keep password setup, sign-out, and the reset flow available during a temporary-password
    # session.
    allowed_views = {
        "accounts:required_password",
        "accounts:organizer_password_change",
        "accounts:logout",
        "accounts:password_reset",
        "accounts:password_reset_done",
        "accounts:password_reset_confirm",
        "accounts:password_reset_complete",
    }

    # Django supplies the next request handler when it builds the middleware chain.
    def __init__(self, get_response):
        self.get_response = get_response

    # Pass each request along so Django can resolve the requested page.
    def __call__(self, request):
        return self.get_response(request)

    # Check the resolved URL before Django runs the view and redirect when a password change
    # is required.
    def process_view(self, request, view_func, view_args, view_kwargs):
        role = account_role(request.user)
        if role not in (Profile.Role.STUDENT, Profile.Role.ORGANIZER):
            return None

        view = request.resolver_match
        # Organizers see the required-password prompt on their dashboard. Students have a
        # dedicated page.
        destination = (
            "events:organizer_dashboard"
            if role == Profile.Role.ORGANIZER else "accounts:required_password"
        )
        if (
            request.user.profile.must_change_password
            and view.url_name
            and view.view_name != destination
            and view.view_name not in self.allowed_views
        ):
            return redirect(destination)
        return None
