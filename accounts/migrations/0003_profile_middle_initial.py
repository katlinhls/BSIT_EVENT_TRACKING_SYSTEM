# Add the optional middle-initial field to Profile.
from django.db import migrations, models


# Django uses this class to apply the database changes in order.
class Migration(migrations.Migration):
    # Apply the previous profile change first.
    dependencies = [
        ("accounts", "0002_profile_must_change_password"),
    ]

    # Add the column so the registration and profile forms can store a middle initial.
    operations = [
        migrations.AddField(
            model_name="profile",
            name="middle_initial",
            field=models.CharField(blank=True, max_length=10),
        ),
    ]
