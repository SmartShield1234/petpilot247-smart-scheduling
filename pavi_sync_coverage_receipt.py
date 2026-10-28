
"""PostgreSQL reconciliation coverage receipt schema.

Development-only schema definition.
No database connection, writes, or booking authorization.
"""

CREATE_COVERAGE_RECEIPTS_TABLE = """
CREATE TABLE IF NOT EXISTS petpilot_sync_coverage_receipts (
    receipt_id BIGSERIAL PRIMARY KEY,
    location_id TEXT NOT NULL,
    calendar_ids JSONB NOT NULL,
    range_start TIMESTAMPTZ NOT NULL,
    range_end TIMESTAMPTZ NOT NULL,
    event_count BIGINT NOT NULL,
    event_max_id BIGINT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'unverified',
    CONSTRAINT valid_receipt_status
        CHECK (status IN ('unverified', 'verified', 'invalidated')),
    CONSTRAINT valid_coverage_range
        CHECK (range_end > range_start)
);
"""


from datetime import datetime, timezone, timedelta
import psycopg


class CoverageReceiptUnavailable(RuntimeError):
    pass


def verify_coverage_receipt(
    *,
    connection_url,
    location_id,
    expected_calendar_ids,
    max_age_minutes=60,
):
    """Read-only verification of an existing reconciliation receipt.

    Does not create receipts, promote sync status, or authorize booking.
    """
    expected = list(expected_calendar_ids)

    if len(expected) != 11 or len(set(expected)) != 11:
        raise CoverageReceiptUnavailable(
            "Exactly 11 unique calendars required"
        )

    if not location_id or not connection_url:
        raise CoverageReceiptUnavailable(
            "Location and database connection required"
        )

    if not 0 < max_age_minutes <= 1440:
        raise CoverageReceiptUnavailable(
            "Invalid freshness limit"
        )

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT receipt_id, calendar_ids,
                           event_count, event_max_id,
                           completed_at, status,
                           snapshot_digest
                    FROM petpilot_sync_coverage_receipts
                    WHERE location_id = %s
                    ORDER BY receipt_id DESC
                    LIMIT 1
                    """,
                    (location_id,),
                )

                receipt = cursor.fetchone()

                if receipt is None:
                    raise CoverageReceiptUnavailable(
                        "No reconciliation receipt available"
                    )

                (
                    receipt_id, calendars, saved_count,
                    saved_max_id, completed_at,
                    status, digest,
                ) = receipt

                if status != "verified":
                    raise CoverageReceiptUnavailable(
                        "Receipt is not verified"
                    )

                if (
                    not isinstance(calendars, list)
                    or len(calendars) != 11
                    or len(set(calendars)) != 11
                    or set(calendars) != set(expected)
                ):
                    raise CoverageReceiptUnavailable(
                        "Calendar coverage mismatch"
                    )

                if (
                    not isinstance(digest, str)
                    or not digest.strip()
                ):
                    raise CoverageReceiptUnavailable(
                        "Snapshot digest missing"
                    )

                if (
                    not isinstance(completed_at, datetime)
                    or completed_at.tzinfo is None
                ):
                    raise CoverageReceiptUnavailable(
                        "Invalid receipt timestamp"
                    )

                age = (
                    datetime.now(timezone.utc)
                    - completed_at.astimezone(timezone.utc)
                )

                if (
                    age < timedelta(0)
                    or age > timedelta(minutes=max_age_minutes)
                ):
                    raise CoverageReceiptUnavailable(
                        "Receipt is stale or future-dated"
                    )

                cursor.execute(
                    """
                    SELECT COUNT(*),
                           COALESCE(MAX(event_log_id), 0)
                    FROM appointment_event_log
                    """
                )

                current_count, current_max_id = cursor.fetchone()

                if (current_count, current_max_id) != (
                    saved_count, saved_max_id
                ):
                    raise CoverageReceiptUnavailable(
                        "Appointment event checkpoint changed"
                    )

    return {
        "receipt_id": receipt_id,
        "calendar_ids": calendars,
        "checkpoint_matches": True,
        "receipt_valid": True,
        "booking_authorized": False,
    }
