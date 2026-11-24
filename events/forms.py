# Prepare the event filter and the form for creating or editing an event.
from django import forms
from django.contrib.auth.models import User

from accounts.access import is_portal_admin
from accounts.models import Profile

from .models import Event


# Completion follows the scheduled end time and is never an input choice.
EVENT_FORM_STATUSES = [
    (status, label) for status, label in Event.Status.choices
    if status != Event.Status.COMPLETED
]


# Allow a dashboard to show all of its events or narrow the analytics to one event.
class AnalyticsFilterForm(forms.Form):
    event = forms.ModelChoiceField(
        queryset=Event.objects.none(), required=False, empty_label="All events",
    )

    # Limit the event choices to the caller's permitted list and include dates in the labels.
    def __init__(self, *args, events, **kwargs):
        super().__init__(*args, **kwargs)
        event_field = self.fields["event"]
        event_field.queryset = events.order_by("-date", "-start_time", "name").only("name", "date")
        event_field.label_from_instance = lambda event: f"{event.name} · {event.date:%b %d, %Y}"


# Collect event details, schedule, optional media, and cancellation status.
class EventForm(forms.ModelForm):

    # Choose the Event model fields and set browser-friendly date and time controls.
    class Meta:
        model = Event

        fields = [
            "name",
            "description",
            "date",
            "end_date",
            "start_time",
            "end_time",
            "stamps_per_student",
            "venue",
            "latitude",
            "longitude",
            "organizer",
            "image",
            "stamp_design",
            "status",
        ]

        labels = {"name": "Event name", "image": "Event image", "date": "Start date"}

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            # The location picker fills these fields when a pin is selected.
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),

            "date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),

            "start_time": forms.TimeInput(
                format="%H:%M:%S", attrs={"type": "time", "step": 1}
            ),

            "end_time": forms.TimeInput(
                format="%H:%M:%S", attrs={"type": "time", "step": 1}
            ),
        }

    # Let administrators assign an organizer. The view assigns ownership for organizer
    # submissions.
    def __init__(self, *args, **kwargs):

        user = kwargs.pop("user", None)

        super().__init__(*args, **kwargs)
        self.fields["stamps_per_student"].required = False
        self.fields["stamps_per_student"].help_text = (
            "Awarded once after both scans on every scheduled day. Enter 0 for an event without stamps."
        )

        if user and not is_portal_admin(user):
            self.fields.pop("organizer")
        else:
            self.fields["organizer"].queryset = User.objects.filter(
                profile__role=Profile.Role.ORGANIZER,
            ).order_by("username")

        # The normal status follows the schedule, with cancellation as a manual choice.
        self.fields["status"].choices = EVENT_FORM_STATUSES
        self.fields["status"].help_text = (
            "Status follows the event's start and end times. Select Cancelled to cancel it."
        )

    def clean_stamps_per_student(self):
        quantity = self.cleaned_data["stamps_per_student"]
        return self.instance.stamps_per_student if quantity is None else quantity
