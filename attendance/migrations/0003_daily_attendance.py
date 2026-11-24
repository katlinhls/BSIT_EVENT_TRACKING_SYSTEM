# Put existing scans on their original attendance day before changing the unique key.
from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def assign_attendance_dates(apps, schema_editor):
    attendance = apps.get_model("attendance", "Attendance")
    records = attendance.objects.using(schema_editor.connection.alias)
    batch = []
    for record in records.select_related("event").iterator(chunk_size=1000):
        event = record.event
        multiple_dates = event.end_date is not None and event.end_date > event.date
        overnight = event.end_time < event.start_time or (
            multiple_dates and event.end_time == event.start_time
        )
        last_day = event.end_date if multiple_dates else event.date
        if multiple_dates and overnight:
            last_day -= timedelta(days=1)
        scan_time = record.in_at or record.out_at
        day = event.date
        if scan_time:
            local_time = timezone.localtime(scan_time, timezone.get_default_timezone())
            day = local_time.date()
            if overnight and local_time.time() < event.end_time:
                day -= timedelta(days=1)
        record.attendance_date = max(event.date, min(day, last_day))
        batch.append(record)
        if len(batch) == 1000:
            records.bulk_update(batch, ["attendance_date"])
            batch.clear()
    if batch:
        records.bulk_update(batch, ["attendance_date"])


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0002_excused_time_out"),
        ("events", "0004_program_schedule_and_stamp_award"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendance", name="attendance_date", field=models.DateField(null=True),
        ),
        migrations.RunPython(assign_attendance_dates),
        migrations.AlterField(
            model_name="attendance", name="attendance_date", field=models.DateField(),
        ),
        migrations.RemoveConstraint(
            model_name="attendance", name="unique_student_event_attendance",
        ),
        migrations.AddConstraint(
            model_name="attendance",
            constraint=models.UniqueConstraint(
                fields=("student", "event", "attendance_date"),
                name="unique_student_event_day_attendance",
            ),
        ),
        migrations.AddIndex(
            model_name="attendance",
            index=models.Index(fields=["event", "attendance_date"], name="attendance_event_day_idx"),
        ),
    ]
