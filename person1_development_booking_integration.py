
"""Person 1: development-only booking integration."""

import os
from datetime import timedelta

import httpx

from ghl_booking_adapter import prepare_ghl_booking_payload
from development_ghl_write_adapter import mock_create_appointment


async def run_development_booking(
    *,
    connection_url,
    location_id,
    calendar_id,
    contact_id,
    groomer_id,
    start_time,
    service_minutes,
    idempotency_key,
    payload_fingerprint,
    reservation_function,
    mock_client,
):
    """Reserve first, then simulate GHL creation."""

    if os.getenv("PETPILOT_ENV") != "development":
        raise RuntimeError("Development mode required")

    if os.getenv("PETPILOT_LIVE_BOOKING_ENABLED") != "false":
        raise RuntimeError("Live booking must remain disabled")

    if not isinstance(mock_client, httpx.AsyncClient):
        raise RuntimeError("A mock HTTP client is required")

    if not isinstance(mock_client._transport, httpx.MockTransport):
        raise RuntimeError("Real HTTP transport prohibited")

    if not isinstance(service_minutes, int) or isinstance(
        service_minutes, bool
    ) or service_minutes <= 0:
        raise ValueError("Invalid service duration")

    end_time = start_time + timedelta(minutes=service_minutes)

    # Validate payload before acquiring a reservation.
    prepared = prepare_ghl_booking_payload(
        location_id=location_id,
        calendar_id=calendar_id,
        contact_id=contact_id,
        groomer_user_id=groomer_id,
        start_time=start_time,
        end_time=end_time,
    )

    reservation = reservation_function(
        connection_url=connection_url,
        location_id=location_id,
        groomer_id=groomer_id,
        start_time=start_time,
        end_time=end_time,
        idempotency_key=idempotency_key,
        payload_fingerprint=payload_fingerprint,
    )

    if reservation.get("status") != "held":
        return {
            "status": "reservation_rejected",
            "reservation_status": reservation.get("status"),
            "booking_authorized": False,
            "real_booking_created": False,
        }

    # Development-only: no real GHL calls.
    try:
        mock_result = await mock_create_appointment(
            mock_client,
            prepared["payload_preview"],
        )
    except Exception:
        # Do not automatically release: the outcome must be
        # reconciled in the actual production workflow.
        return {
            "status": "mock_creation_failed",
            "reservation_id": reservation.get("reservation_id"),
            "requires_reconciliation": True,
            "booking_authorized": False,
            "real_booking_created": False,
        }

    event = mock_result.get("mock_response", {}).get("event")

    if not isinstance(event, dict) or not isinstance(
        event.get("id"), str
    ) or not event["id"].strip():
        return {
            "status": "mock_response_invalid",
            "reservation_id": reservation.get("reservation_id"),
            "requires_reconciliation": True,
            "booking_authorized": False,
            "real_booking_created": False,
        }

    for key in (
        "locationId", "calendarId", "contactId",
        "assignedUserId", "startTime", "endTime",
    ):
        if event.get(key) != prepared["payload_preview"][key]:
            return {
                "status": "mock_response_invalid",
                "reservation_id": reservation.get("reservation_id"),
                "requires_reconciliation": True,
                "booking_authorized": False,
                "real_booking_created": False,
            }

    return {
        "status": "development_mock_created",
        "reservation_id": reservation.get("reservation_id"),
        "mock_appointment_id": event["id"],
        "requires_reconciliation": True,
        "booking_authorized": False,
        "real_booking_created": False,
    }
