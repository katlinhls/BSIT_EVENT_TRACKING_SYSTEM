# Add the flag that prompts accounts with temporary passwords to choose a new one.
from django.db import migrations, models


# Django uses this class to apply the database changes in order.
class Migration(migrations.Migration):
    # Apply the migration that creates Profile before adding the flag.
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    # Add the flag with a default of false for existing profiles.
    operations = [
        migrations.AddField(
            model_name="profile",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
    ]
