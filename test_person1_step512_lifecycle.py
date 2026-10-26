
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from postgres_booking_coordinator import reserve_booking_atomically
from postgres_booking_locks import (
    confirm_booking_lock,
    release_booking_lock,
)

load_dotenv(
    dotenv_path=Path(__file__).resolve().parent / ".env",
    override=False,
)


def main():
    if os.getenv("PETPILOT_ENV") != "development":
        raise RuntimeError("Development environment required")

    if os.getenv("PETPILOT_LIVE_BOOKING_ENABLED") != "false":
        raise RuntimeError("Live booking must remain disabled")

    url = os.getenv("PETPILOT_POSTGRES_URL")
    if not url:
        raise RuntimeError("PostgreSQL URL missing")

    print("===== PERSON 1 - STEP 5.12 =====")

    unique = uuid4().hex
    start = datetime.now(timezone.utc) + timedelta(days=40)
    start = start.replace(second=0, microsecond=0)

    reservation = reserve_booking_atomically(
        connection_url=url,
        location_id="test-location-" + unique,
        groomer_id="test-groomer",
        start_time=start,
        end_time=start + timedelta(minutes=90),
        idempotency_key="test-lifecycle-" + unique,
        payload_fingerprint="test-fingerprint-" + unique,
    )

    assert reservation["status"] == "held", reservation
    reservation_id = reservation["reservation_id"]
    print("Development reservation created: PASS")

    # This tests PostgreSQL state transitions only.
    # It does not certify an actual GHL appointment.
    confirmed = confirm_booking_lock(
        connection_url=url,
        reservation_id=reservation_id,
        schema="petpilot_lock_test",
    )

    assert confirmed["status"] == "confirmed", confirmed
    print("Reservation confirmation transition: PASS")

    released = release_booking_lock(
        connection_url=url,
        reservation_id=reservation_id,
        schema="petpilot_lock_test",
    )

    assert released["status"] == "not_released", released
    print("Confirmed reservation protected from release: PASS")

    unknown = confirm_booking_lock(
        connection_url=url,
        reservation_id=str(uuid4()),
        schema="petpilot_lock_test",
    )

    assert unknown["status"] == "not_confirmed", unknown
    print("Unknown reservation rejected: PASS")

    print("Real GHL appointment created: False")
    print("Live booking authorized: False")
    print("STEP 5.12 PASSED")


if __name__ == "__main__":
    main()
