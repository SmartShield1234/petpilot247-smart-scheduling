import hashlib
import json
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from contextlib import closing
import os


DATABASE_PATH = Path(
    os.environ.get(
        "PETPILOT_DATABASE_PATH",
        str(
            Path(__file__).resolve().parent
            / "petpilot247_appointments_dev.db"
        ),
    )
).resolve()



def initialize_appointment_ledger(db_path=DATABASE_PATH):
    """
    Create the development appointment ledger.

    Local database only.
    No GHL or Google Maps API calls.
    """

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                location_id TEXT NOT NULL,
                appointment_id TEXT NOT NULL,
                calendar_id TEXT NOT NULL,
                assigned_user_id TEXT,
                contact_id TEXT,
                appointment_status TEXT,
                start_time TEXT,
                end_time TEXT,
                date_updated TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'webhook',
                PRIMARY KEY (location_id, appointment_id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS appointment_event_log (
                event_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_id TEXT NOT NULL,
                appointment_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                received_at TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            )
        """)

def record_appointment_create(
    validated_event,
    db_path=DATABASE_PATH,
):
    """
    Store a validated fictional AppointmentCreate event.

    The caller must verify the webhook signature before invoking this.
    This function does not make external API calls.
    """

    if validated_event.get("event_type") != "AppointmentCreate":
        raise ValueError("Expected AppointmentCreate event")

    appointment = validated_event["appointment"]
    location_id = validated_event["location_id"]
    appointment_id = validated_event["appointment_id"]

    event_hash = hashlib.sha256(
        json.dumps(
            validated_event,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    received_at = datetime.now(timezone.utc).isoformat()

    connection = sqlite3.connect(db_path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT 1 FROM appointments
            WHERE location_id = ? AND appointment_id = ?
            """,
            (location_id, appointment_id),
        ).fetchone()

        if existing:
            previous_event = connection.execute(
                """
                SELECT 1
                FROM appointment_event_log
                WHERE event_hash = ?
                  AND location_id = ?
                  AND appointment_id = ?
                  AND event_type = 'AppointmentCreate'
                """,
                (event_hash, location_id, appointment_id),
            ).fetchone()

            if previous_event:
                connection.commit()
                return "duplicate_ignored"

            raise ValueError(
                "Appointment already exists with different event data; "
                "reconciliation required"
            )

        connection.execute(
            """
            INSERT INTO appointment_event_log (
                location_id, appointment_id, event_type,
                received_at, event_hash
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                location_id,
                appointment_id,
                "AppointmentCreate",
                received_at,
                event_hash,
            ),
        )

        connection.execute(
            """
            INSERT INTO appointments (
                location_id, appointment_id, calendar_id,
                assigned_user_id, contact_id, appointment_status,
                start_time, end_time, date_updated, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                appointment.get("dateUpdated"),
                "webhook",
            ),
        )

        connection.commit()
        return "created"

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def record_appointment_update(validated_event, db_path=DATABASE_PATH):
    """
    Apply a validated AppointmentUpdate to an existing appointment.

    Caller must authenticate the webhook before calling this function.
    Missing, stale, or conflicting timestamps fail closed.
    """

    if validated_event.get("event_type") != "AppointmentUpdate":
        raise ValueError("Expected AppointmentUpdate event")

    appointment = validated_event["appointment"]
    location_id = validated_event["location_id"]
    appointment_id = validated_event["appointment_id"]

    def parse_timestamp(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Appointment update timestamp required")

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("Invalid update timestamp") from exc

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timezone-aware update timestamp required")

        return parsed

    new_updated = parse_timestamp(appointment.get("dateUpdated"))

    connection = sqlite3.connect(db_path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT date_updated, is_deleted
            FROM appointments
            WHERE location_id = ? AND appointment_id = ?
            """,
            (location_id, appointment_id),
        ).fetchone()

        if existing is None:
            raise ValueError(
                "Unknown appointment; reconciliation required"
            )

        previous_updated, is_deleted = existing

        if is_deleted:
            raise ValueError(
                "Deleted appointment cannot be updated without reconciliation"
            )

        previous_timestamp = parse_timestamp(previous_updated)

        if new_updated <= previous_timestamp:
            # Accept an identical retry only when the exact event
            # was previously recorded in the event log.
            event_hash = hashlib.sha256(
                json.dumps(
                    validated_event,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()

            previous_event = connection.execute(
                """
                SELECT 1
                FROM appointment_event_log
                WHERE event_hash = ?
                  AND location_id = ?
                  AND appointment_id = ?
                  AND event_type = 'AppointmentUpdate'
                """,
                (event_hash, location_id, appointment_id),
            ).fetchone()

            if previous_event:
                connection.commit()
                return "duplicate_ignored"

            raise ValueError(
                "Stale or conflicting appointment update"
            )

        event_hash = hashlib.sha256(
            json.dumps(
                validated_event,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        received_at = datetime.now(timezone.utc).isoformat()

        connection.execute(
            """
            INSERT INTO appointment_event_log (
                location_id, appointment_id, event_type,
                received_at, event_hash
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                location_id,
                appointment_id,
                "AppointmentUpdate",
                received_at,
                event_hash,
            ),
        )

        connection.execute(
            """
            UPDATE appointments
            SET calendar_id = ?,
                assigned_user_id = ?,
                contact_id = ?,
                appointment_status = ?,
                start_time = ?,
                end_time = ?,
                date_updated = ?
            WHERE location_id = ? AND appointment_id = ?
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

        connection.commit()
        return "updated"

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def record_appointment_delete(validated_event, db_path=DATABASE_PATH):
    """
    Preserve a deleted appointment as an audit tombstone.

    The caller must authenticate the GHL webhook first.
    Incomplete or conflicting deletions require reconciliation.
    """

    if validated_event.get("event_type") != "AppointmentDelete":
        raise ValueError("Expected AppointmentDelete event")

    appointment = validated_event["appointment"]
    location_id = validated_event["location_id"]
    appointment_id = validated_event["appointment_id"]

    timestamp = appointment.get("dateUpdated")

    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("Deletion timestamp required")

    try:
        deleted_at = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Invalid deletion timestamp") from exc

    if deleted_at.tzinfo is None or deleted_at.utcoffset() is None:
        raise ValueError("Timezone-aware deletion timestamp required")

    event_hash = hashlib.sha256(
        json.dumps(
            validated_event,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    connection = sqlite3.connect(db_path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT date_updated, is_deleted
            FROM appointments
            WHERE location_id = ? AND appointment_id = ?
            """,
            (location_id, appointment_id),
        ).fetchone()

        if existing is None:
            raise ValueError(
                "Unknown deleted appointment; reconciliation required"
            )

        previous_updated, is_deleted = existing

        if is_deleted:
            previous_event = connection.execute(
                """
                SELECT 1 FROM appointment_event_log
                WHERE event_hash = ?
                  AND location_id = ?
                  AND appointment_id = ?
                  AND event_type = 'AppointmentDelete'
                """,
                (event_hash, location_id, appointment_id),
            ).fetchone()

            if previous_event:
                connection.commit()
                return "duplicate_ignored"

            raise ValueError(
                "Appointment already deleted; reconciliation required"
            )

        if not isinstance(previous_updated, str):
            raise ValueError(
                "Previous update timestamp missing; reconciliation required"
            )

        try:
            previous_time = datetime.fromisoformat(
                previous_updated.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("Invalid previous timestamp") from exc

        if previous_time.tzinfo is None or previous_time.utcoffset() is None:
            raise ValueError("Previous timestamp requires timezone")

        if deleted_at <= previous_time:
            raise ValueError("Stale or conflicting deletion event")

        received_at = datetime.now(timezone.utc).isoformat()

        connection.execute(
            """
            INSERT INTO appointment_event_log (
                location_id, appointment_id, event_type,
                received_at, event_hash
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                location_id,
                appointment_id,
                "AppointmentDelete",
                received_at,
                event_hash,
            ),
        )

        connection.execute(
            """
            UPDATE appointments
            SET is_deleted = 1,
                date_updated = ?
            WHERE location_id = ? AND appointment_id = ?
            """,
            (timestamp, location_id, appointment_id),
        )

        connection.commit()
        return "deleted"

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

if __name__ == "__main__":
    initialize_appointment_ledger()
    print("Development appointment ledger created | PASS")
    print("Appointment event log created | PASS")
    print("No real GHL appointments modified.")
