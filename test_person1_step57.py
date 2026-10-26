
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from postgres_booking_coordinator import reserve_booking_atomically
from person1_development_booking_integration import (
    run_development_booking,
)

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=Path(__file__).resolve().parent / ".env",
    override=False,
)


async def main():
    assert os.getenv("PETPILOT_ENV") == "development"
    assert os.getenv("PETPILOT_LIVE_BOOKING_ENABLED") == "false"

    connection_url = os.getenv("PETPILOT_POSTGRES_URL")
    if not connection_url:
        raise RuntimeError("PETPILOT_POSTGRES_URL is missing")

    print("===== PERSON 1 - STEP 5.7 =====")

    unique = uuid4().hex
    start = datetime.now(timezone.utc) + timedelta(days=30)
    start = start.replace(second=0, microsecond=0)

    mock_calls = []

    def handler(request):
        payload = json.loads(request.content)
        mock_calls.append(payload)

        return httpx.Response(
            200,
            json={
                "event": {
                    "id": "mock-" + unique,
                    **payload,
                }
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:

        params = {
            "connection_url": connection_url,
            "location_id": "test-location-" + unique,
            "calendar_id": "test-calendar",
            "contact_id": "test-contact",
            "groomer_id": "test-groomer",
            "start_time": start,
            "service_minutes": 90,
            "idempotency_key": "test-key-" + unique,
            "payload_fingerprint": "test-fingerprint-" + unique,
            "reservation_function": reserve_booking_atomically,
            "mock_client": client,
        }

        first = await run_development_booking(**params)
        second = await run_development_booking(**params)

    assert first["status"] == "development_mock_created", first
    assert second["status"] == "reservation_rejected", second
    assert second["reservation_status"] == "existing"
    assert len(mock_calls) == 1

    print("Real PostgreSQL reservation: PASS")
    print("Duplicate idempotency protection: PASS")
    print("Mock GHL creation count:", len(mock_calls))
    print("Real GHL booking created: False")
    print("Live booking authorized: False")
    print("STEP 5.7 PASSED")


if __name__ == "__main__":
    asyncio.run(main())
