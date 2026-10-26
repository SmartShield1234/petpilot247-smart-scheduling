
"""Fail-closed full-window appointment conflict validator."""

from datetime import datetime, timedelta, timezone


def validate_appointment_window(
    *,
    groomer_id: str,
    requested_start: datetime,
    service_minutes: int,
    appointments: list,
    setup_minutes: int = 15,
    cleanup_minutes: int = 15,
) -> dict:
    rejected = {
        "status": "rejected",
        "window_available": False,
        "booking_authorized": False,
    }

    if not isinstance(groomer_id, str) or not groomer_id.strip():
        return {**rejected, "reason": "Invalid groomer"}

    if not isinstance(requested_start, datetime) or requested_start.tzinfo is None:
        return {**rejected, "reason": "Invalid appointment start"}

    for value in (service_minutes, setup_minutes, cleanup_minutes):
        if type(value) is not int or value < 0:
            return {**rejected, "reason": "Invalid duration"}

    if service_minutes <= 0:
        return {**rejected, "reason": "Service duration required"}

    if not isinstance(appointments, list):
        return {**rejected, "reason": "Invalid appointment data"}

    start = requested_start.astimezone(timezone.utc) - timedelta(
        minutes=setup_minutes
    )

    end = requested_start.astimezone(timezone.utc) + timedelta(
        minutes=service_minutes + cleanup_minutes
    )

    for appointment in appointments:
        if not isinstance(appointment, dict):
            return {**rejected, "reason": "Invalid appointment record"}

        assigned = appointment.get("assigned_user_id")
        status = str(appointment.get("appointment_status", "")).lower()

        # Cancelled appointments do not block, but unknown
        # statuses remain blocking for safety.
        if status == "cancelled":
            continue

        if not assigned:
            return {**rejected, "reason": "Unassigned blocking appointment"}

        if assigned != groomer_id:
            continue

        existing_start = appointment.get("start_time")
        existing_end = appointment.get("end_time")

        if (
            not isinstance(existing_start, datetime)
            or not isinstance(existing_end, datetime)
            or existing_start.tzinfo is None
            or existing_end.tzinfo is None
            or existing_end <= existing_start
        ):
            return {**rejected, "reason": "Invalid existing appointment time"}

        existing_start = existing_start.astimezone(timezone.utc)
        existing_end = existing_end.astimezone(timezone.utc)

        if start < existing_end and existing_start < end:
            return {
                **rejected,
                "reason": "Appointment window overlaps existing booking",
            }

    return {
        "status": "window_available",
        "window_available": True,
        "booking_authorized": False,
    }
