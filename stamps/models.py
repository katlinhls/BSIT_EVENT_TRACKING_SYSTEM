# Store the stamps students earn by completing attendance at events.
from django.core.validators import MinValueValidator
from django.db import models
from accounts.models import Profile
from events.models import Event

# Store the quantity the student received when this event was checked out.
class EventStamp(models.Model):
    student = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="event_stamps")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="stamps")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    earned_at = models.DateTimeField(auto_now_add=True)

    # Keep one award per student and event and display recent awards first.
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "event"],
                name="unique_student_event_stamp",
            ),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="stamp_award_positive_quantity"),
        ]
        ordering = ["-earned_at", "-pk"]

    # Use the student and event names as the stamp's readable label.
    def __str__(self):
        return f"{self.student.display_name} - {self.event.name}"
