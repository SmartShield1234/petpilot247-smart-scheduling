
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx

from person1_development_booking_integration import (
    run_development_booking,
)


async def main():
    os.environ["PETPILOT_ENV"] = "development"
    os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] = "false"

    print("===== PERSON 1 - STEP 5.6 =====")

    state = {"reserved": False, "mock_calls": 0}

    def fake_reservation(**kwargs):
        if state["reserved"]:
            return {
                "status": "existing",
                "booking_authorized": False,
            }

        state["reserved"] = True
        return {
            "status": "held",
            "reservation_id": "test-reservation-001",
            "booking_authorized": False,
        }

    def handler(request):
        state["mock_calls"] += 1
        payload = json.loads(request.content)

        return httpx.Response(
            200,
            json={
                "event": {
                    "id": "mock-event-001",
                    **payload,
                }
            },
        )

    start = datetime.now(timezone.utc) + timedelta(days=3)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:

        args = {
            "connection_url": "mock-database",
            "location_id": "test-location",
            "calendar_id": "test-calendar",
            "contact_id": "test-contact",
            "groomer_id": "test-groomer",
            "start_time": start,
            "service_minutes": 90,
            "idempotency_key": "test-key-001",
            "payload_fingerprint": "test-fingerprint",
            "reservation_function": fake_reservation,
            "mock_client": client,
        }

        first = await run_development_booking(**args)
        second = await run_development_booking(**args)

    assert first["status"] == "development_mock_created", first
    assert second["status"] == "reservation_rejected", second
    assert second["reservation_status"] == "existing"
    assert state["mock_calls"] == 1

    assert first["booking_authorized"] is False
    assert first["real_booking_created"] is False

    print("Reservation acquired before mock creation: PASS")
    print("Duplicate request blocked: PASS")
    print("Only one mock appointment created: PASS")
    print("Real booking created: False")
    print("Live booking authorized: False")
    print("STEP 5.6 PASSED")


asyncio.run(main())
