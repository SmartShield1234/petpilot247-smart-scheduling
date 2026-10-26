
"""PetPilot247 internal scheduling provider.

Development staging only.
No external caller can bypass groomer approval.
No live booking operations.
"""

from ghl_staff_inventory_adapter import get_calendar_staff


async def check_internal_scheduling_readiness(
    *,
    calendar_id: str,
    groomer_id: str,
) -> dict:
    """Validate authoritative inventory gates before scheduling."""

    def blocked(reason: str) -> dict:
        return {
            "status": "blocked",
            "reason": reason,
            "booking_authorized": False,
        }

    if not isinstance(calendar_id, str) or not calendar_id.strip():
        return blocked("Missing calendar ID")

    if not isinstance(groomer_id, str) or not groomer_id.strip():
        return blocked("Missing groomer ID")

    try:
        staff = get_calendar_staff(calendar_id=calendar_id)
    except (ValueError, KeyError, TypeError, OSError):
        return blocked("Calendar inventory unavailable or invalid")

    if not isinstance(staff, dict):
        return blocked("Invalid calendar inventory")

    assigned_ids = staff.get("assigned_ghl_user_ids")

    if not isinstance(assigned_ids, list):
        return blocked("Assigned groomer mapping unavailable")

    if groomer_id not in assigned_ids:
        return blocked("Groomer not assigned to calendar")

    if staff.get("production_approved") is not True:
        return blocked("Groomer calendar approval pending")

    if staff.get("geographic_verified") is not True:
        return blocked("Geographic eligibility not verified")

    # Approval alone is not proof of fresh calendar evidence,
    # a valid service address, or a safe travel window.
    return {
        "status": "approval_gates_passed",
        "calendar_id": calendar_id,
        "groomer_id": groomer_id,
        "ready_for_evidence_fetch": True,
        "booking_authorized": False,
    }


async def run_internal_scheduling_recheck(
    *,
    calendar_id: str,
    groomer_id: str,
    requested_start,
    customer_address: str,
    service_minutes: int,
    availability: dict,
    appointments: list,
    previous_appointment: dict,
    next_appointment: dict,
    maps_api_key: str,
    evidence_fetched_at,
) -> dict:
    """Run approval checks before evaluating supplied test evidence."""

    approval = await check_internal_scheduling_readiness(
        calendar_id=calendar_id,
        groomer_id=groomer_id,
    )

    if approval.get("status") != "approval_gates_passed":
        return {
            "status": "blocked",
            "reason": approval.get("reason", "Approval not verified"),
            "booking_authorized": False,
        }

    from ghl_combined_scheduling_recheck import (
        combined_scheduling_recheck,
    )

    result = await combined_scheduling_recheck(
        calendar_id=calendar_id,
        groomer_id=groomer_id,
        requested_start=requested_start,
        customer_address=customer_address,
        service_minutes=service_minutes,
        availability=availability,
        appointments=appointments,
        previous_appointment=previous_appointment,
        next_appointment=next_appointment,
        maps_api_key=maps_api_key,
        evidence_verified=False,
        evidence_fetched_at=evidence_fetched_at,
    )

    return result
