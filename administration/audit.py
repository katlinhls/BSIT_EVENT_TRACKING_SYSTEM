# Shared helper for adding consistent entries to the activity log.
from .models import ActivityLog


# Copy the actor's username, the subject label, and any changed values into a new entry.
def record_activity(actor, action, subject, details="", changes=None):
    return ActivityLog.objects.create(
        actor=actor,
        actor_username=actor.get_username(),
        action=action,
        subject=str(subject),
        details=details,
        changes=changes or {},
    )
