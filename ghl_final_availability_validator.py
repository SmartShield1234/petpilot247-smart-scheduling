
"""Fail-closed GHL availability validation for PetPilot247."""

from datetime import datetime, timezone


def validate_final_ghl_availability(
    *,
    calendar_id: str,
    groomer_id: str,
    requested_start: datetime,
    availability: dict,
) -> dict:

    rejected = {
        "status": "rejected",
        "start_time_available": False,
        "booking_authorized": False,
    }

    if not isinstance(calendar_id, str) or not calendar_id.strip():
        return {**rejected, "reason": "Missing calendar"}

    if not isinstance(groomer_id, str) or not groomer_id.strip():
        return {**rejected, "reason": "Missing groomer"}

    if not isinstance(requested_start, datetime):
        return {**rejected, "reason": "Invalid start time"}

    if requested_start.tzinfo is None:
        return {**rejected, "reason": "Timezone required"}

    if not isinstance(availability, dict):
        return {**rejected, "reason": "Invalid availability response"}

    if availability.get("verification_status") != "free_slots_only":
        return {**rejected, "reason": "Unexpected verification status"}

    calendars = availability.get("calendar_availability")

    if not isinstance(calendars, dict):
        return {**rejected, "reason": "Missing availability data"}

    groomer = calendars.get(groomer_id)

    if not isinstance(groomer, dict):
        return {**rejected, "reason": "Groomer availability missing"}

    slots_by_date = groomer.get("slots_by_date")

    if not isinstance(slots_by_date, dict):
        return {**rejected, "reason": "Missing slot data"}

    requested_utc = requested_start.astimezone(timezone.utc)

    for slots in slots_by_date.values():
        if not isinstance(slots, list):
            continue

        for slot in slots:
            if not isinstance(slot, datetime):
                continue

            if slot.tzinfo is None:
                continue

            if slot.astimezone(timezone.utc) == requested_utc:
                return {
                    "status": "start_time_available",
                    "calendar_id": calendar_id,
                    "groomer_id": groomer_id,
                    "start_time_available": True,
                    "booking_authorized": False,
                }

    return {**rejected, "reason": "Requested start time unavailable"}
