
"""PetPilot247 PostgreSQL booking locks.

Staging implementation. No GHL booking writes.
All timestamps must be timezone-aware.
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import psycopg


def booking_lock_table(schema: str) -> str:
    """Allow only the two known PetPilot247 schemas."""
    if schema not in ("petpilot_lock_test", "public"):
        raise ValueError("Invalid booking-lock schema")

    return f"{schema}.petpilot_booking_locks"

def initialize_booking_locks(
    connection_url: str,
    schema: str = "petpilot_lock_test",
):
    """Create the PostgreSQL booking reservation table."""

    
    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
        options=f"-csearch_path={schema}",
    ) as conn:

        with conn.transaction(), conn.cursor() as cur:
            cur.execute("""
                CREATE EXTENSION IF NOT EXISTS btree_gist
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS petpilot_booking_locks (
                    reservation_id UUID PRIMARY KEY,
                    location_id TEXT NOT NULL,
                    groomer_id TEXT NOT NULL,
                    start_time TIMESTAMPTZ NOT NULL,
                    end_time TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL DEFAULT 'held',
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (end_time > start_time),
                    CHECK (status IN ('held', 'confirmed', 'released')),
                        booking_lock_table(schema)
                )
            """)

            cur.execute("""
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'petpilot_no_overlapping_bookings'
                  AND conrelid = 'petpilot_booking_locks'::regclass
            """)

            if cur.fetchone() is None:
                cur.execute("""
                    ALTER TABLE petpilot_booking_locks
                    ADD CONSTRAINT petpilot_no_overlapping_bookings
                    EXCLUDE USING gist (
                        location_id WITH =,
                        groomer_id WITH =,
                        tstzrange(start_time, end_time, '[)') WITH &&
                    )
                    WHERE (status IN ('held', 'confirmed'))
                """)


def acquire_booking_lock(
    *,
    connection_url: str,
    location_id: str,
    groomer_id: str,
    start_time: datetime,
    end_time: datetime,
    hold_minutes: int = 5,
    schema: str = "petpilot_lock_test",
):

    """Attempt to reserve a groomer time window atomically."""
    booking_lock_table(schema)
    if not location_id or not groomer_id:
        raise ValueError("Location and groomer IDs required")
    if (
        not isinstance(hold_minutes, int)
        or isinstance(hold_minutes, bool)
        or not 1 <= hold_minutes <= 30
    ):
        raise ValueError("Hold duration must be 1 to 30 minutes")
    if (
        start_time.tzinfo is None
        or end_time.tzinfo is None
        or end_time <= start_time
    ):
        raise ValueError("Valid timezone-aware time window required")

    reservation_id = uuid4()

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
        options=f"-csearch_path={schema}",
    ) as conn:
        with conn.transaction(), conn.cursor() as cur:
            
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
                            reservation_id,
                            location_id,
                            groomer_id,
                            start_time,
                            end_time,
                            expires_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            NOW() + (%s * INTERVAL '1 minute')
                        )
                    """, (
                        reservation_id,
                        location_id,
                        groomer_id,
                        start_time,
                        end_time,
                        hold_minutes,
                    ))

            except psycopg.errors.ExclusionViolation:
                return {
                    "status": "conflict",
                    "booking_authorized": False,
                }

    return {
        "status": "held",
        "reservation_id": str(reservation_id),
        "booking_authorized": False,
    }



def confirm_booking_lock(
    *,
    connection_url: str,
    reservation_id: str,
    schema: str = "petpilot_lock_test",
) -> dict:
    """Confirm only an active, unexpired reservation."""

    booking_lock_table(schema)

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
        options=f"-csearch_path={schema}",
    ) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("""
                UPDATE petpilot_booking_locks
                SET status = 'confirmed'
                WHERE reservation_id = %s
                  AND status = 'held'
                  AND expires_at > NOW()
                RETURNING reservation_id
            """, (reservation_id,))

            confirmed = cur.fetchone()

    return {
        "status": "confirmed" if confirmed else "not_confirmed",
        "booking_authorized": False,
    }


def release_booking_lock(
    *,
    connection_url: str,
    reservation_id: str,
    schema: str = "petpilot_lock_test",
) -> dict:
    """Release only temporary holds, not confirmed bookings."""

    booking_lock_table(schema)

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
        options=f"-csearch_path={schema}",
    ) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("""
                UPDATE petpilot_booking_locks
                SET status = 'released'
                WHERE reservation_id = %s
                  AND status = 'held'
                RETURNING reservation_id
            """, (reservation_id,))

            released = cur.fetchone()

    return {
        "status": "released" if released else "not_released",
        "booking_authorized": False,
    }
