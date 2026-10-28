
"""PostgreSQL idempotency for PetPilot247 booking attempts.

Staging only. Does not create appointments or authorize bookings.
"""

from uuid import uuid4

import psycopg


def claim_postgres_booking_attempt(
    *,
    connection_url: str,
    location_id: str,
    idempotency_key: str,
    payload_fingerprint: str,
    schema: str = "petpilot_lock_test",
) -> dict:
    """Create one attempt or retrieve the existing attempt safely."""

    if schema != "petpilot_lock_test":
        raise ValueError("Only the isolated test schema is allowed")

    for name, value in (
        ("location_id", location_id),
        ("idempotency_key", idempotency_key),
        ("payload_fingerprint", payload_fingerprint),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")

        if len(value) > 256:
            raise ValueError(f"{name} is too long")

    new_attempt_id = uuid4()

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
        options="-csearch_path=petpilot_lock_test",
    ) as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO petpilot_booking_attempts (
                    attempt_id,
                    location_id,
                    idempotency_key,
                    payload_fingerprint,
                    status
                )
                VALUES (%s, %s, %s, %s, 'pending')
                ON CONFLICT (location_id, idempotency_key)
                DO NOTHING
                RETURNING attempt_id
            """, (
                new_attempt_id,
                location_id,
                idempotency_key,
                payload_fingerprint,
            ))

            inserted = cur.fetchone()

            cur.execute("""
                SELECT
                    attempt_id,
                    payload_fingerprint,
                    status,
                    reservation_id,
                    ghl_appointment_id
                FROM petpilot_booking_attempts
                WHERE location_id = %s
                  AND idempotency_key = %s
            """, (location_id, idempotency_key))

            existing = cur.fetchone()

            if existing is None:
                raise RuntimeError("Booking attempt could not be located")

    attempt_id, stored_fingerprint, status, reservation_id, appointment_id = existing

    if stored_fingerprint != payload_fingerprint:
        return {
            "status": "payload_conflict",
            "attempt_id": None,
            "booking_authorized": False,
        }

    return {
        "status": "created" if inserted else "existing",
        "attempt_id": str(attempt_id),
        "attempt_status": status,
        "reservation_id": str(reservation_id) if reservation_id else None,
        "appointment_recorded": bool(appointment_id),
        "booking_authorized": False,
    }
