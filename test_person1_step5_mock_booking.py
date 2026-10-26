
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx

from ghl_booking_adapter import prepare_ghl_booking_payload
from development_ghl_write_adapter import mock_create_appointment


async def main():
    assert os.getenv("PETPILOT_ENV") == "development"
    assert os.getenv("PETPILOT_LIVE_BOOKING_ENABLED") == "false"

    print("===== PERSON 1 - STEP 5.4 =====")

    start = datetime.now(timezone.utc) + timedelta(days=3)
    end = start + timedelta(minutes=90)

    prepared = prepare_ghl_booking_payload(
        location_id="test-location",
        calendar_id="test-calendar",
        contact_id="test-contact",
        groomer_user_id="test-groomer",
        start_time=start,
        end_time=end,
    )

    assert prepared["simulation_only"] is True
    assert prepared["booking_authorized"] is False
    assert prepared["submitted"] is False

    print("Booking payload preparation: PASS")

    requests_received = []

    def mock_handler(request):
        requests_received.append(request)

        assert request.method == "POST"
        assert request.url.path == "/calendars/events/appointments"

        payload = json.loads(request.content)
        assert payload == prepared["payload_preview"]

        return httpx.Response(
            200,
            json={
                "event": {
                    "id": "mock-appointment-001",
                    **payload,
                }
            },
        )

    transport = httpx.MockTransport(mock_handler)

    async with httpx.AsyncClient(transport=transport) as client:
        result = await mock_create_appointment(
            client,
            prepared["payload_preview"],
        )

    assert len(requests_received) == 1
    assert result["real_booking_created"] is False
    assert result["booking_authorized"] is False

    appointment = result["mock_response"]["event"]

    assert appointment["id"] == "mock-appointment-001"
    assert appointment["calendarId"] == "test-calendar"
    assert appointment["assignedUserId"] == "test-groomer"

    print("Mock GHL appointment creation: PASS")
    print("Mock response verification: PASS")
    print("Real booking created: False")
    print("Live booking authorized: False")
    print("STEP 5.4 PASSED")


if __name__ == "__main__":
    asyncio.run(main())
