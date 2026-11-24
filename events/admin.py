# Configure Django's built-in admin so authorized staff can find events by name, schedule,
# venue, and status.
from django.contrib import admin

from .forms import EVENT_FORM_STATUSES
from .models import Event

# Register this model with columns, filters, and searchable fields for its admin list.
@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "start_time", "venue", "organizer", "status")
    list_filter = ("status", "date")
    search_fields = ("name", "venue", "description")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "status":
            kwargs["choices"] = EVENT_FORM_STATUSES
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if {"date", "end_date", "start_time", "end_time", "organizer", "status"}.intersection(form.changed_data):
            obj.early_time_out_until = None
        obj.sync_status(save=False)
        super().save_model(request, obj, form, change)

    # Keep completed events read-only in the built-in admin as well.
    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or not obj.is_completed)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not obj.is_completed)
