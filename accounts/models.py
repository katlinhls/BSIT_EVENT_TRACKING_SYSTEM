# Define the extra account details and in-app messages stored in the database.
from django.contrib.auth.models import User
from django.db import models

# Link each Django user to one role, student details when applicable, and a profile image.
class Profile(models.Model):
    # Keep the role values and display labels together for permission checks and forms.
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        ORGANIZER = "ORGANIZER", "Event Organizer"
        STUDENT = "STUDENT", "Student"

    # The related name lets a view reach this record with request.user.profile.
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    # Student IDs are unique. Organizer and administrator profiles can leave the student
    # details blank.
    student_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    middle_initial = models.CharField(max_length=10, blank=True)
    program = models.CharField(max_length=100, blank=True)
    year_level = models.CharField(max_length=50, blank=True)
    profile_image = models.ImageField(upload_to="profiles/", null=True, blank=True)
    # Organizer accounts created by the administrator must change their
    # temporary password on their first successful login.
    must_change_password = models.BooleanField(default=False)

    # Check the saved role when setting the first-login password flag for organizers.
    def save(self, *args, **kwargs):
        # Newly-created organizers, and profiles switched to the organizer
        # role, are required to choose their own password before continuing.
        if self.role == self.Role.ORGANIZER:
            if self._state.adding:
                self.must_change_password = True
            else:
                try:
                    old_role = type(self).objects.get(pk=self.pk).role
                    if old_role != self.Role.ORGANIZER:
                        self.must_change_password = True
                except type(self).DoesNotExist:
                    self.must_change_password = True
        super().save(*args, **kwargs)

    # Use the account name and role as the readable label for this profile.
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.role}"

    # Show the full name when available and fall back to the username.
    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username


# Store one inbox message for a user along with its delivery time and read state.
class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="event_notifications")
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, null=True, blank=True)
    event_end_at = models.DateTimeField(null=True, blank=True)
    subject = models.CharField(max_length=220)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    # Show the newest messages first, using the ID to order ties.
    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event", "event_end_at"], name="unique_event_end_reminder",
            ),
        ]
