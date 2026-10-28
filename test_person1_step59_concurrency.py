
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from postgres_booking_coordinator import reserve_booking_atomically
from person1_development_booking_integration import (
    run_development_booking,
)

load_dotenv(
    dotenv_path=Path(__file__).resolve().parent / ".env",
    override=False,
)

assert os.getenv("PETPILOT_ENV") == "development"
assert os.getenv("PETPILOT_LIVE_BOOKING_ENABLED") == "false"

database_url = os.getenv("PETPILOT_POSTGRES_URL")
if not database_url:
    raise RuntimeError("PostgreSQL configuration missing")

# Run only against the approved petpilot_lock_test schema.
location_id = "test-location-" + uuid4().hex
groomer_id = "test-groomer"
start_time = (
    datetime.now(timezone.utc) + timedelta(days=35)
).replace(second=0, microsecond=0)

counter = {"mock_calls": 0}
counter_lock = Lock()


async def make_request(request_number):
    def mock_handler(request):
        with counter_lock:
            counter["mock_calls"] += 1

        payload = json.loads(request.content)

        return httpx.Response(
            200,
            json={
                "event": {
                    "id": "mock-" + uuid4().hex,
                    **payload,
                }
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler)
    ) as client:
        return await run_development_booking(
            connection_url=database_url,
            location_id=location_id,
            calendar_id="test-calendar",
            contact_id=f"test-contact-{request_number}",
            groomer_id=groomer_id,
            start_time=start_time,
            service_minutes=90,
            idempotency_key=f"test-key-{request_number}",
            payload_fingerprint=f"test-fingerprint-{request_number}",
            reservation_function=reserve_booking_atomically,
            mock_client=client,
        )


def worker(number):
    return asyncio.run(make_request(number))


def main():
    print("===== PERSON 1 - STEP 5.9 =====")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [1, 2]))

    statuses = [result["status"] for result in results]

    assert statuses.count("development_mock_created") == 1, results
    assert statuses.count("reservation_rejected") == 1, results

    rejected = next(
        result for result in results
        if result["status"] == "reservation_rejected"
    )
    assert rejected["reservation_status"] == "conflict", results

    assert counter["mock_calls"] == 1
    assert all(
        result["booking_authorized"] is False
        and result["real_booking_created"] is False
        for result in results
    )

    print("Concurrent PostgreSQL reservations: PASS")
    print("Overlapping reservation rejected: PASS")
    print("Only one mock GHL creation: PASS")
    print("Real GHL booking created: False")
    print("STEP 5.9 CONCURRENCY PASSED")


if __name__ == "__main__":
    main()
