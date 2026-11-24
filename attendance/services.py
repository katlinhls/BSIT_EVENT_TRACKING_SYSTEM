# Create and check the short-lived QR tokens and synchronize stamps with attendance records.
import base64
import hashlib
import hmac
import json
import time
from django.conf import settings

from stamps.models import EventStamp

from .models import Attendance

# Convert the project's signing key to bytes for the signature calculation.
def _secret():
    return settings.SECRET_KEY.encode()

def create_qr_token(student_profile):
    """
    Creates a short-lived signed token.
    The student ID is encoded only as a server-verifiable payload;
    it is not exposed as a plain QR value.
    """
    now = int(time.time())
    # Divide the current timestamp into QR validity windows. The next window begins at expiry.
    bucket = now // settings.QR_VALIDITY_SECONDS
    payload = {
        "uid": student_profile.user_id,
        "bucket": bucket,
        "exp": (bucket + 1) * settings.QR_VALIDITY_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    # Sign the serialized data so the server can detect changes to the QR contents.
    signature = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"

# Check the signature and expiry before returning the data used to identify a student.
def validate_qr_token(token):
    try:
        encoded, signature = token.split(".", 1)
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode())

        # Recreate the expected signature and compare it before reading the token data.
        expected = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None, "Invalid QR token."

        payload = json.loads(raw.decode())
        if int(time.time()) >= int(payload["exp"]):
            return None, "QR code expired. Ask the student to refresh their QR."

        # Only the current time bucket is accepted.
        current_bucket = int(time.time()) // settings.QR_VALIDITY_SECONDS
        if int(payload["bucket"]) != current_bucket:
            return None, "QR code expired. Ask the student to refresh their QR."

        return payload, None
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, base64.binascii.Error):
        return None, "Invalid QR token."


def qr_token_expiry(token):
    """Return the expiry timestamp embedded in a token for UI synchronization."""
    try:
        encoded, _ = token.split(".", 1)
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode())
        payload = json.loads(raw.decode())
        return int(payload["exp"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError,
            base64.binascii.Error, UnicodeDecodeError):
        return 0


# Award the program's stamp quantity once all scheduled days have both scans.
def sync_attendance_stamp(record):
    lookup = {"student_id": record.student_id, "event_id": record.event_id}
    if not record.completed:
        EventStamp.objects.filter(**lookup).delete()
        return 0

    event = record.event
    if event.attendance_day_count > 1:
        completed = Attendance.completed_days(event).filter(student_id=record.student_id).count()
        if completed != event.attendance_day_count:
            return 0

    quantity = event.stamps_per_student
    if quantity == 0:
        # Keep a previous award if the organizer later changes the event's setting.
        return EventStamp.objects.filter(**lookup).values_list("quantity", flat=True).first() or 0

    award, _ = EventStamp.objects.get_or_create(**lookup, defaults={"quantity": quantity})
    return award.quantity
