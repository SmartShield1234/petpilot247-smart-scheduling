"""Map GHL appointment details to historical snapshot records.

Pure conversion only. No GHL calls, SQLite writes, or sync approval.
"""

from historical_reconciliation import parse_timestamp


def map_ghl_historical_snapshot(event):
    if not isinstance(event, dict):
        raise ValueError("Invalid GHL appointment")

    required_identifiers = (
        "locationId",
        "id",
        "calendarId",
    )

    for field in required_identifiers:
        value = event.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing GHL field: {field}")

    if event.get("deleted") is True:
        raise ValueError(
            "Deleted appointment requires explicit reconciliation"
        )

    start = parse_timestamp(event.get("startTime"))
    end = parse_timestamp(event.get("endTime"))
    updated = parse_timestamp(event.get("dateUpdated"))

    if end <= start:
        raise ValueError("Invalid appointment time range")

    optional_fields = (
        "assignedUserId",
        "contactId",
        "appointmentStatus",
    )

    for field in optional_fields:
        value = event.get(field)

        if value is not None and not isinstance(value, str):
            raise ValueError(f"Invalid GHL field: {field}")

    return {
        "location_id": event["locationId"].strip(),
        "appointment_id": event["id"].strip(),
        "calendar_id": event["calendarId"].strip(),
        "assigned_user_id": event.get("assignedUserId"),
        "contact_id": event.get("contactId"),
        "appointment_status": event.get("appointmentStatus"),
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "date_updated": updated.isoformat(),
    }
