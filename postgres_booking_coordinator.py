
"""Atomic PetPilot247 staging booking coordinator.

No HighLevel appointment creation.
No live booking authorization.
"""

from datetime import datetime
from uuid import uuid4

import psycopg


def reserve_booking_atomically(
    *,
    connection_url: str,
    location_id: str,
    groomer_id: str,
    start_time: datetime,
    end_time: datetime,
    idempotency_key: str,
    payload_fingerprint: str,
) -> dict:
    """Claim the request and hold the slot in one transaction."""

    for name, value in (
        ("location_id", location_id),
        ("groomer_id", groomer_id),
        ("idempotency_key", idempotency_key),
        ("payload_fingerprint", payload_fingerprint),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        if len(value) > 256:
            raise ValueError(f"{name} is too long")

    if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
        raise ValueError("Invalid appointment times")

    if (
        start_time.tzinfo is None
        or end_time.tzinfo is None
        or end_time <= start_time
    ):
        raise ValueError("Timezone-aware appointment window required")

    attempt_id = uuid4()
    reservation_id = uuid4()

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
        options="-csearch_path=petpilot_lock_test",
    ) as conn:
        with conn.transaction(), conn.cursor() as cur:

            cur.execute("""
                INSERT INTO petpilot_booking_attempts (
                    attempt_id, location_id, idempotency_key,
                    payload_fingerprint, status
                )
                VALUES (%s, %s, %s, %s, 'pending')
                ON CONFLICT (location_id, idempotency_key)
                DO NOTHING
                RETURNING attempt_id
            """, (
                attempt_id, location_id,
                idempotency_key, payload_fingerprint,
            ))

            created = cur.fetchone()

            cur.execute("""
                SELECT attempt_id, payload_fingerprint,
                       status, reservation_id
                FROM petpilot_booking_attempts
                WHERE location_id = %s
                  AND idempotency_key = %s
                FOR UPDATE
            """, (location_id, idempotency_key))

            record = cur.fetchone()
            if record is None:
                raise RuntimeError("Booking attempt not found")

            existing_id, fingerprint, status, existing_reservation = record

            if fingerprint != payload_fingerprint:
                return {
                    "status": "payload_conflict",
                    "booking_authorized": False,
                }

            if created is None:
                return {
                    "status": "existing",
                    "attempt_id": str(existing_id),
                    "attempt_status": status,
                    "reservation_id": (
                        str(existing_reservation)
                        if existing_reservation else None
                    ),
                    "booking_authorized": False,
                }

            cur.execute("""
                UPDATE petpilot_booking_locks
                SET status = 'released'
                WHERE location_id = %s
                  AND groomer_id = %s
                  AND status = 'held'
                  AND expires_at <= NOW()
            """, (location_id, groomer_id))

            try:
                with conn.transaction():
                    cur.execute("""
                        INSERT INTO petpilot_booking_locks (
                            reservation_id, location_id, groomer_id,
                            start_time, end_time, expires_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            NOW() + INTERVAL '5 minutes'
                        )
                    """, (
                        reservation_id, location_id, groomer_id,
                        start_time, end_time,
                    ))

            except psycopg.errors.ExclusionViolation:
                cur.execute("""
                    UPDATE petpilot_booking_attempts
                    SET status = 'failed', updated_at = NOW()
                    WHERE attempt_id = %s
                """, (attempt_id,))

                return {
                    "status": "conflict",
                    "booking_authorized": False,
                }

            cur.execute("""
                UPDATE petpilot_booking_attempts
                SET status = 'held',
                    reservation_id = %s,
                    updated_at = NOW()
                WHERE attempt_id = %s
            """, (reservation_id, attempt_id))

    return {
        "status": "held",
        "attempt_id": str(attempt_id),
        "reservation_id": str(reservation_id),
        "booking_authorized": False,
    }
