# Create the EventStamp table for student awards tied to an event.
from django.db import migrations, models
import django.db.models.deletion

# Django uses this class to apply the database changes in order.
class Migration(migrations.Migration):
    initial = True
    # Create the profile and event tables before linking a stamp to them.
    dependencies = [
        ("accounts", "0001_initial"),
        ("events", "0001_initial"),
    ]
    # Store the award time and enforce a single stamp for each student and event.
    operations = [
        migrations.CreateModel(
            name="EventStamp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("earned_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stamps", to="events.event")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="event_stamps", to="accounts.profile")),
            ],
            options={"ordering": ["-earned_at"]},
        ),
        migrations.AddConstraint(
            model_name="eventstamp",
            constraint=models.UniqueConstraint(fields=("student", "event"), name="unique_student_event_stamp"),
        ),
    ]
