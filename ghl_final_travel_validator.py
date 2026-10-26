
"""Two-direction travel feasibility for PetPilot247.

Fail closed when route evidence is missing or invalid.
Does not authorize live booking.
"""
import math
from datetime import datetime, timedelta, timezone

from maps_service import get_driving_minutes, MapsServiceError


async def validate_groomer_travel(
    *,
    requested_start: datetime,
    customer_address: str,
    service_minutes: int,
    setup_minutes: int,
    cleanup_minutes: int,
    previous_appointment: dict,
    next_appointment: dict,
    maps_api_key: str,
) -> dict:

    rejected = {
        "status": "rejected",
        "travel_verified": False,
        "booking_authorized": False,
    }

    if not isinstance(requested_start, datetime) or requested_start.tzinfo is None:
        return {**rejected, "reason": "Invalid start time"}

    if not isinstance(customer_address, str) or not customer_address.strip():
        return {**rejected, "reason": "Customer address missing"}

    if not isinstance(maps_api_key, str) or not maps_api_key.strip():
        return {**rejected, "reason": "Google Maps API key missing"}

    if any(
        type(value) is not int or value < 0
        for value in (service_minutes, setup_minutes, cleanup_minutes)
    ) or service_minutes == 0:
        return {**rejected, "reason": "Invalid service duration"}

    if not isinstance(previous_appointment, dict) or not isinstance(next_appointment, dict):
        return {**rejected, "reason": "Adjacent appointment evidence missing"}

    for appointment, time_field in (
        (previous_appointment, "end_time"),
        (next_appointment, "start_time"),
    ):
        if (
            not isinstance(appointment.get("address"), str)
            or not appointment["address"].strip()
        ):
            return {**rejected, "reason": "Adjacent appointment address missing"}

        value = appointment.get(time_field)
        if not isinstance(value, datetime) or value.tzinfo is None:
            return {**rejected, "reason": "Adjacent appointment time missing"}


    try:
        route_before = await get_driving_minutes(
            previous_appointment["address"],
            customer_address,
            maps_api_key,
        )

        route_after = await get_driving_minutes(
            customer_address,
            next_appointment["address"],
            maps_api_key,
        )

        if not isinstance(route_before, dict):
            raise ValueError("Invalid previous route response")

        if not isinstance(route_after, dict):
            raise ValueError("Invalid next route response")

        minutes_before = route_before.get("driving_minutes")
        minutes_after = route_after.get("driving_minutes")

    except (MapsServiceError, ValueError, TypeError):
        return {
            **rejected,
            "reason": "Google Maps route verification failed",
        }
    
    if (
        type(minutes_before) not in (int, float)
        or type(minutes_after) not in (int, float)
    ):
        return {
            **rejected,
            "reason": "Invalid driving durations",
        }

    if not all(
        math.isfinite(value)
        for value in (minutes_before, minutes_after)
    ):
        return {
            **rejected,
            "reason": "Non-finite driving duration",
        }

    if minutes_before < 0 or minutes_after < 0:
        return {
            **rejected,
            "reason": "Negative driving duration",
        }


    start = requested_start.astimezone(timezone.utc)
    previous_end = previous_appointment["end_time"].astimezone(timezone.utc)
    next_start = next_appointment["start_time"].astimezone(timezone.utc)

    required_start = previous_end + timedelta(
        minutes=minutes_before + setup_minutes
    )

    required_end = start + timedelta(
        minutes=service_minutes + cleanup_minutes + minutes_after
    )

    if start < required_start or required_end > next_start:
        return {**rejected, "reason": "Travel or grooming window does not fit"}

    return {
        "status": "travel_feasible",
        "travel_verified": True,
        "minutes_from_previous": minutes_before,
        "minutes_to_next": minutes_after,
        "booking_authorized": False,
    }
