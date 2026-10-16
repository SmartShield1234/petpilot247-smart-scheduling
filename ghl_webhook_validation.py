
from datetime import datetime


ALLOWED_EVENTS = {
    "AppointmentCreate",
    "AppointmentUpdate",
    "AppointmentDelete",
}


def validate_appointment_webhook(payload, expected_location_id):
    """
    Validate appointment webhook structure.

    Call this only AFTER signature verification.
    No database writes or external API requests.
    """

    if not isinstance(payload, dict):
        raise ValueError("Invalid webhook payload")

    event_type = payload.get("type")

    if event_type not in ALLOWED_EVENTS:
        raise ValueError("Unsupported appointment event")

    location_id = payload.get("locationId")

    if (
        not isinstance(location_id, str)
        or not location_id
        or location_id != expected_location_id
    ):
        raise ValueError("Invalid webhook location")

    appointment = payload.get("appointment")

    if not isinstance(appointment, dict):
        raise ValueError("Missing appointment object")

    for field in ("id", "calendarId"):
        value = appointment.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing appointment {field}")

    for field in ("startTime", "endTime"):
        value = appointment.get(field)

        if not isinstance(value, str):
            raise ValueError(f"Missing appointment {field}")

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"Invalid appointment {field}") from exc

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"Timezone required for {field}")

    start = datetime.fromisoformat(
        appointment["startTime"].replace("Z", "+00:00")
    )
    end = datetime.fromisoformat(
        appointment["endTime"].replace("Z", "+00:00")
    )

    if start >= end:
        raise ValueError("Invalid appointment time range")

    return {
        "event_type": event_type,
        "location_id": location_id,
        "appointment_id": appointment["id"],
        "calendar_id": appointment["calendarId"],
        "appointment": appointment,
    }
