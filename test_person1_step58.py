
import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx

from person1_development_booking_integration import (
    run_development_booking,
)


async def main():
    os.environ["PETPILOT_ENV"] = "development"
    os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] = "false"

    print("===== PERSON 1 - STEP 5.8 =====")

    start = datetime.now(timezone.utc) + timedelta(days=7)
    calls = {"count": 0}

    def base_args(reservation_function, client):
        return {
            "connection_url": "simulated-db",
            "location_id": "fictional-location",
            "calendar_id": "fictional-calendar",
            "contact_id": "fictional-contact",
            "groomer_id": "fictional-groomer",
            "start_time": start,
            "service_minutes": 90,
            "idempotency_key": "fictional-key",
            "payload_fingerprint": "fictional-fingerprint",
            "reservation_function": reservation_function,
            "mock_client": client,
        }

    def conflict_reservation(**kwargs):
        return {
            "status": "conflict",
            "booking_authorized": False,
        }

    def held_reservation(**kwargs):
        return {
            "status": "held",
            "reservation_id": "fictional-reservation",
            "booking_authorized": False,
        }

    def conflict_handler(request):
        calls["count"] += 1
        raise AssertionError(
            "GHL must not be called for a conflicted slot"
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(conflict_handler)
    ) as client:
        result = await run_development_booking(
            **base_args(conflict_reservation, client)
        )

    assert result["status"] == "reservation_rejected", result
    assert result["reservation_status"] == "conflict"
    assert calls["count"] == 0
    print("Conflicting slot blocks GHL creation: PASS")

    def failed_handler(request):
        return httpx.Response(
            503, json={"message": "Simulated GHL outage"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(failed_handler)
    ) as client:
        result = await run_development_booking(
            **base_args(held_reservation, client)
        )

    assert result["status"] == "mock_creation_failed", result
    assert result["requires_reconciliation"] is True
    assert result["real_booking_created"] is False
    print("GHL failure handled safely: PASS")

    def invalid_handler(request):
        return httpx.Response(
            200, json={"event": {"id": "fictional-event"}}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(invalid_handler)
    ) as client:
        result = await run_development_booking(
            **base_args(held_reservation, client)
        )

    assert result["status"] == "mock_response_invalid", result
    assert result["requires_reconciliation"] is True
    assert result["real_booking_created"] is False
    print("Incomplete GHL response rejected: PASS")

    def timeout_handler(request):
        raise httpx.ReadTimeout("Simulated timeout")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(timeout_handler)
    ) as client:
        result = await run_development_booking(
            **base_args(held_reservation, client)
        )

    assert result["status"] == "mock_creation_failed", result
    assert result["requires_reconciliation"] is True
    print("Unknown booking outcome flagged: PASS")

    print("Real PostgreSQL writes: None")
    print("Live GHL booking authorized: False")
    print("STEP 5.8 PASSED")


if __name__ == "__main__":
    asyncio.run(main())
