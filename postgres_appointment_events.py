
"""PostgreSQL appointment event processing.

Input must come from the authenticated GHL webhook validator.
This module does not authenticate webhook signatures itself.
"""

import hashlib
import json
from datetime import datetime, timezone

import psycopg


def parse_revision(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Appointment revision required")

    revision = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if revision.tzinfo is None or revision.utcoffset() is None:
        raise ValueError("Timezone-aware revision required")

    return revision.astimezone(timezone.utc)


def record_postgres_appointment_event(
    *,
    connection_url,
    validated_event,
):
    event_type = validated_event.get("event_type")

    if event_type not in {
        "AppointmentCreate",
        "AppointmentUpdate",
        "AppointmentDelete",
    }:
        raise ValueError("Unsupported appointment event")

    location_id = validated_event["location_id"]
    appointment_id = validated_event["appointment_id"]
    appointment = validated_event["appointment"]

    if not all(
        isinstance(value, str) and value.strip()
        for value in (location_id, appointment_id)
    ):
        raise ValueError("Invalid appointment identity")

    revision = parse_revision(
        appointment.get("dateUpdated")
    )

    event_hash = hashlib.sha256(
        json.dumps(
            validated_event,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
    ) as conn:

        with conn.transaction():
            with conn.cursor() as cursor:

                # Coordinate webhook writes with reconciliation.
                # Shared transaction lock allows independent
                # webhook operations while excluding a recovery
                # process holding the corresponding exclusive lock.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock_shared(%s)",
                    (247777,),
                )

                # Serialize writers for the same appointment identity.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(%s, 0))",
                    (location_id + ":" + appointment_id,),
                )

                cursor.execute(
                    """
                    SELECT date_updated, is_deleted
                    FROM appointments
                    WHERE location_id = %s
                      AND appointment_id = %s
                    FOR UPDATE
                    """,
                    (location_id, appointment_id),
                )

                existing = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT 1 FROM appointment_event_log
                    WHERE location_id = %s
                      AND appointment_id = %s
                      AND event_type = %s
                      AND event_hash = %s
                    """,
                    (
                        location_id,
                        appointment_id,
                        event_type,
                        event_hash,
                    ),
                )

                if cursor.fetchone():
                    return "duplicate_ignored"

                if event_type == "AppointmentCreate":
                    if existing is not None:
                        raise ValueError(
                            "Existing appointment requires reconciliation"
                        )

                else:
                    if existing is None:
                        raise ValueError(
                            "Unknown appointment requires reconciliation"
                        )

                    previous_revision, is_deleted = existing

                    if is_deleted:
                        raise ValueError(
                            "Deleted appointment requires reconciliation"
                        )

                    previous = parse_revision(previous_revision)

                    if revision <= previous:
                        raise ValueError(
                            "Stale or conflicting appointment event"
                        )

                if event_type == "AppointmentDelete":
                    cursor.execute(
                        """
                        UPDATE appointments
                        SET is_deleted = 1,
                            date_updated = %s
                        WHERE location_id = %s
                          AND appointment_id = %s
                        """,
                        (
                            appointment["dateUpdated"],
                            location_id,
                            appointment_id,
                        ),
                    )
                    result = "deleted"

                elif event_type == "AppointmentCreate":
                    cursor.execute(
                        """
                        INSERT INTO appointments (
                            location_id, appointment_id,
                            calendar_id, assigned_user_id,
                            contact_id, appointment_status,
                            start_time, end_time,
                            date_updated, is_deleted, source
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, 0, 'webhook'
                        )
                        """,
                        (
                            location_id,
                            appointment_id,
                            appointment["calendarId"],
                            appointment.get("assignedUserId"),
                            appointment.get("contactId"),
                            appointment.get("appointmentStatus"),
                            appointment["startTime"],
                            appointment["endTime"],
                            appointment["dateUpdated"],
                        ),
                    )
                    result = "created"

                else:
                    cursor.execute(
                        """
                        UPDATE appointments
                        SET calendar_id = %s,
                            assigned_user_id = %s,
                            contact_id = %s,
                            appointment_status = %s,
                            start_time = %s,
                            end_time = %s,
                            date_updated = %s
                        WHERE location_id = %s
                          AND appointment_id = %s
                        """,
                        (
                            appointment["calendarId"],
                            appointment.get("assignedUserId"),
                            appointment.get("contactId"),
                            appointment.get("appointmentStatus"),
                            appointment["startTime"],
                            appointment["endTime"],
                            appointment["dateUpdated"],
                            location_id,
                            appointment_id,
                        ),
                    )
                    result = "updated"

                # The same transaction must invalidate any
                # previous service-address confirmation.
                if event_type in {
                    "AppointmentUpdate",
                    "AppointmentDelete",
                }:
                    cursor.execute(
                        """
                        DELETE FROM service_address_confirmations
                        WHERE location_id = %s
                          AND appointment_id = %s
                        """,
                        (location_id, appointment_id),
                    )

                cursor.execute(
                    """
                    INSERT INTO appointment_event_log (
                        location_id, appointment_id,
                        event_type, received_at, event_hash
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        location_id,
                        appointment_id,
                        event_type,
                        datetime.now(timezone.utc).isoformat(),
                        event_hash,
                    ),
                )

                return result



def mark_postgres_sync_uncertain(*, connection_url, reason):
    """Persist an unsafe synchronization state."""

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Synchronization failure reason required")

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE appointment_sync_health
                    SET status = 'uncertain',
                        reason = %s,
                        last_reconciled_at = NULL,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        reason.strip(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "Synchronization health record missing"
                    )


def require_postgres_verified_sync(*, connection_url):
    """Refuse unverified or uncertain synchronization."""

    with psycopg.connect(
        connection_url,
        sslmode="require",
        connect_timeout=15,
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, last_reconciled_at
                FROM appointment_sync_health
                WHERE id = 1
                """
            )

            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Synchronization health missing")

    status, reconciled_at = row

    if status != "verified" or not reconciled_at:
        raise RuntimeError(
            "Appointment synchronization is not verified"
        )

    return True
