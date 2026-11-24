# Shared role checks keep permissions and dashboard routing consistent across the apps.
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache

from .models import Profile


# Get the role for a signed-in, active user. Django superusers have the administrator role.
def account_role(user):
    if not user.is_authenticated or not user.is_active:
        return None
    if user.is_superuser:
        return Profile.Role.ADMIN
    profile = getattr(user, "profile", None)
    return profile.role if profile else None


# Use the same administrator check in views and forms.
def is_portal_admin(user):
    return account_role(user) == Profile.Role.ADMIN


# Map a role to its named dashboard URL. Users without a role go to the landing page.
def dashboard_name(user):
    return {
        Profile.Role.ADMIN: "administration:dashboard",
        Profile.Role.ORGANIZER: "events:organizer_dashboard",
        Profile.Role.STUDENT: "stamps:student_dashboard",
    }.get(account_role(user), "home")


# Wrap a view with the admin sign-in screen, a role check, and private-page cache rules.
def administrator_required(view):
    # Run the requested view after the session has been checked for administrator access.
    @login_required(login_url="administration:login")
    @never_cache
    @wraps(view)
    def checked(request, *args, **kwargs):
        if not is_portal_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return checked


# Share the current user's role with templates so the menu can show the matching links.
def navigation(request):
    return {"portal_role": account_role(request.user)}
