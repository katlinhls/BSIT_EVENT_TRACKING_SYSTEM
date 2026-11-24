# Store a dated history of management actions, attendance scans, and corrections.
from django.conf import settings
from django.db import models
from django.utils.dateparse import parse_datetime


# Record the actor, action, subject, and optional details for each audited change.
class ActivityLog(models.Model):
    # Define the saved action codes and the labels shown to administrators.
    class Action(models.TextChoices):
        ACCOUNT_CREATED = "ACCOUNT_CREATED", "Account created"
        ACCOUNT_UPDATED = "ACCOUNT_UPDATED", "Account updated"
        ACCOUNT_ENABLED = "ACCOUNT_ENABLED", "Account activated"
        ACCOUNT_DISABLED = "ACCOUNT_DISABLED", "Account deactivated"
        ACCOUNT_DELETED = "ACCOUNT_DELETED", "Account deleted"
        PASSWORD_RESET = "PASSWORD_RESET", "Password set"
        RESET_LINK_SENT = "RESET_LINK_SENT", "Reset link sent"
        EVENT_CREATED = "EVENT_CREATED", "Event created"
        EVENT_UPDATED = "EVENT_UPDATED", "Event updated"
        EVENT_DELETED = "EVENT_DELETED", "Event deleted"
        ATTENDANCE_CORRECTED = "ATTENDANCE_CORRECTED", "Attendance corrected"
        CHECK_IN = "CHECK_IN", "Time in recorded"
        CHECK_OUT = "CHECK_OUT", "Time out recorded"
        EARLY_TIME_OUT_APPROVED = "EARLY_TIME_OUT_APPROVED", "Early Time Out approved"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    # Keep the username on the log entry so the actor label survives account deletion.
    actor_username = models.CharField(max_length=150)
    action = models.CharField(max_length=30, choices=Action.choices)
    subject = models.TextField()
    details = models.TextField(blank=True)
    # Store field-by-field changes together with the rest of the audit entry.
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Read logs in reverse chronological order with the ID as a tie-breaker.
    class Meta:
        ordering = ["-created_at", "-pk"]

    # Keep checkout labels as text and convert timestamp changes back to dates.
    @property
    def attendance_changes(self):
        changes = []
        for label, values in self.changes.items():
            before, after = values["before"], values["after"]
            is_timestamp = label != "Time Out type"
            changes.append({
                "label": label,
                "before": parse_datetime(before) if is_timestamp and before else before,
                "after": parse_datetime(after) if is_timestamp and after else after,
                "is_timestamp": is_timestamp,
            })
        return changes
