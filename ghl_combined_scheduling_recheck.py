
"""PetPilot247 combined scheduling recheck.

Development validation only.
Inputs must come from trusted integrations, not customers.
Never authorizes live booking.
"""

from datetime import datetime, timezone, timedelta

from ghl_final_availability_validator import (
    validate_final_ghl_availability,
)
from ghl_appointment_window_validator import (
    validate_appointment_window,
)
from ghl_final_travel_validator import (
    validate_groomer_travel,
)


async def combined_scheduling_recheck(
    *,
    calendar_id: str,
    groomer_id: str,
    requested_start: datetime,
    customer_address: str,
    service_minutes: int,
    availability: dict,
    appointments: list,
    previous_appointment: dict,
    next_appointment: dict,
    maps_api_key: str,
    evidence_verified: bool = False,
    evidence_fetched_at: datetime = None,
    setup_minutes: int = 15,
    cleanup_minutes: int = 15,
) -> dict:

    def reject(reason):
        return {
            "status": "rejected",
            "reason": reason,
            "booking_authorized": False,
        }

    # Fail closed unless the integration layer has established
    # trustworthy source identity and complete appointment data.
    if evidence_verified is not True:
        return reject("Scheduling evidence not verified")

    if (
        not isinstance(evidence_fetched_at, datetime)
        or evidence_fetched_at.tzinfo is None
    ):
        return reject("Evidence timestamp missing")

    age = datetime.now(timezone.utc) - evidence_fetched_at.astimezone(
        timezone.utc
    )

    if not timedelta(seconds=0) <= age <= timedelta(seconds=60):
        return reject("Scheduling evidence stale or invalid")

    availability_result = validate_final_ghl_availability(
        calendar_id=calendar_id,
        groomer_id=groomer_id,
        requested_start=requested_start,
        availability=availability,
    )

    if not availability_result.get("start_time_available"):
        return reject("GHL start time unavailable")

    window_result = validate_appointment_window(
        groomer_id=groomer_id,
        requested_start=requested_start,
        service_minutes=service_minutes,
        appointments=appointments,
        setup_minutes=setup_minutes,
        cleanup_minutes=cleanup_minutes,
    )

    if not window_result.get("window_available"):
        return reject("Appointment window conflict")

    travel_result = await validate_groomer_travel(
        requested_start=requested_start,
        customer_address=customer_address,
        service_minutes=service_minutes,
        setup_minutes=setup_minutes,
        cleanup_minutes=cleanup_minutes,
        previous_appointment=previous_appointment,
        next_appointment=next_appointment,
        maps_api_key=maps_api_key,
    )

    if not travel_result.get("travel_verified"):
        return reject("Travel feasibility not verified")

    return {
        "status": "development_checks_passed",
        "start_time_available": True,
        "window_available": True,
        "travel_feasible": True,
        "booking_authorized": False,
    }
