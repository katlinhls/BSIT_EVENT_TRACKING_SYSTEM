# Configure Django's built-in admin so authorized staff can find earned stamps by student,
# event, and date.
from django.contrib import admin
from .models import EventStamp

# Register this model with columns, filters, and searchable fields for its admin list.
@admin.register(EventStamp)
class EventStampAdmin(admin.ModelAdmin):
    list_display = ("student", "event", "quantity", "earned_at")
    list_filter = ("event", "earned_at")
    search_fields = ("student__student_id", "student__user__first_name", "student__user__last_name", "event__name")
