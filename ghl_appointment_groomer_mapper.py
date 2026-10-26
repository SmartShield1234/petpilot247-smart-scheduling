
"""Fail-closed appointment-to-groomer mapping for PetPilot247."""

from ghl_staff_inventory_adapter import get_calendar_staff


def map_appointment_to_groomer(appointment: dict) -> dict:
    if not isinstance(appointment, dict):
        raise ValueError("Invalid appointment record")

    calendar_id = (
        appointment.get("calendar_id")
        or appointment.get("calendarId")
    )

    groomer_id = (
        appointment.get("assigned_user_id")
        or appointment.get("assignedUserId")
    )

    rejected = {
        "status": "rejected",
        "identity_matched": False,
        "booking_authorized": False,
    }

    if not isinstance(calendar_id, str) or not calendar_id.strip():
        return {**rejected, "reason": "Missing calendar ID"}

    if not isinstance(groomer_id, str) or not groomer_id.strip():
        return {**rejected, "reason": "Missing assigned groomer"}

    
    try:
        staff = get_calendar_staff(calendar_id=calendar_id)
    except ValueError:
        return {
            **rejected,
            "reason": "Unknown or duplicated calendar",
        }


    if not isinstance(staff, dict):
        return {**rejected, "reason": "Invalid staff inventory"}

    allowed_ids = staff.get("assigned_ghl_user_ids")

    if not isinstance(allowed_ids, list):
        return {**rejected, "reason": "Missing verified staff list"}

    if groomer_id not in allowed_ids:
        return {
            **rejected,
            "reason": "Assigned groomer not in calendar inventory",
        }

    approved = staff.get("production_approved") is True
    geographic = staff.get("geographic_verified") is True

    return {
        "status": (
            "pending_approval"
            if not (approved and geographic)
            else "identity_verified"
        ),
        "calendar_id": calendar_id,
        "groomer_id": groomer_id,
        "identity_matched": True,
        "production_approved": approved,
        "geographic_verified": geographic,
        "booking_authorized": False,
    }
