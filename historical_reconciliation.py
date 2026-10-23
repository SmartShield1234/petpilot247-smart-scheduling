
from datetime import datetime
import sqlite3
from pathlib import Path
from appointment_ledger import DATABASE_PATH

SNAPSHOT_FIELDS = (
    "calendar_id",
    "assigned_user_id",
    "contact_id",
    "appointment_status",
    "start_time",
    "end_time",
    "date_updated",
)


def parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing appointment timestamp")

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Invalid appointment timestamp") from exc

    if parsed.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")

    return parsed


def decide_historical_reconciliation(existing, incoming):
    """
    Decide what to do with a historical GHL API snapshot.

    Returns a decision only.
    Does not modify SQLite or GHL.
    """

    if not isinstance(incoming, dict):
        raise ValueError("Invalid incoming appointment")

    if existing is not None and not isinstance(existing, dict):
        raise ValueError("Invalid existing appointment")

    for field in ("location_id", "appointment_id", *SNAPSHOT_FIELDS):
        if field not in incoming:
            raise ValueError(f"Missing incoming field: {field}")

    if not incoming["location_id"] or not incoming["appointment_id"]:
        raise ValueError("Missing appointment identity")

    incoming_time = parse_timestamp(incoming["date_updated"])

    start = parse_timestamp(incoming["start_time"])
    end = parse_timestamp(incoming["end_time"])

    if end <= start:
        raise ValueError("Invalid appointment time range")

    if existing is None:
        return "insert_new"

    if (
        incoming["location_id"] != existing.get("location_id")
        or incoming["appointment_id"] != existing.get("appointment_id")
    ):
        raise ValueError("Appointment identity mismatch")

    if existing.get("is_deleted"):
        return "manual_review_deleted"

    existing_time = parse_timestamp(existing.get("date_updated"))

    if incoming_time < existing_time:
        return "reject_stale"

    if incoming_time > existing_time:
        return "manual_review_newer"

    # Equal timestamp: compare normalized timestamps and all fields.
    for field in SNAPSHOT_FIELDS:
        if field in ("start_time", "end_time", "date_updated"):
            if parse_timestamp(incoming[field]) != parse_timestamp(
                existing.get(field)
            ):
                return "reject_conflicting"
        elif incoming[field] != existing.get(field):
            return "reject_conflicting"

    return "ignore_identical"



def reconcile_historical_snapshot(
    incoming,
    db_path=DATABASE_PATH,
):
    """
    Reconcile one historical GHL API snapshot.

    - Uses a single SQLite write transaction.
    - Never changes authenticated webhook event history.
    - Does not overwrite existing appointments.
    - Fails closed on conflicts.
    """

    database = Path(db_path).resolve()

    # Historical reconciliation must not run against the
    # primary development appointment ledger.
    if database == Path(DATABASE_PATH).resolve():
        raise ValueError(
            "Historical reconciliation against main ledger is disabled"
        )

    if not database.is_file():
        raise ValueError(
            "Temporary ledger must be initialized before reconciliation"
        )

    connection = sqlite3.connect(database)

    try:
        connection.execute("BEGIN IMMEDIATE")

        connection.row_factory = sqlite3.Row

        if not isinstance(incoming, dict):
            raise ValueError("Invalid historical appointment")

        location_id = incoming.get("location_id")
        appointment_id = incoming.get("appointment_id")

        if not isinstance(location_id, str) or not location_id.strip():
            raise ValueError("Missing location ID")

        if not isinstance(appointment_id, str) or not appointment_id.strip():
            raise ValueError("Missing appointment ID")

        existing_row = connection.execute(
            """
            SELECT *
            FROM appointments
            WHERE location_id = ?
              AND appointment_id = ?
            """,
            (location_id, appointment_id),
        ).fetchone()

        existing = (
            dict(existing_row)
            if existing_row is not None
            else None
        )

        decision = decide_historical_reconciliation(
            existing,
            incoming,
        )

        if decision == "insert_new":
            connection.execute(
                """
                INSERT INTO appointments (
                    location_id,
                    appointment_id,
                    calendar_id,
                    assigned_user_id,
                    contact_id,
                    appointment_status,
                    start_time,
                    end_time,
                    date_updated,
                    is_deleted,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incoming["location_id"],
                    incoming["appointment_id"],
                    incoming["calendar_id"],
                    incoming["assigned_user_id"],
                    incoming["contact_id"],
                    incoming["appointment_status"],
                    incoming["start_time"],
                    incoming["end_time"],
                    incoming["date_updated"],
                    0,
                    "historical_api_backfill",
                ),
            )

            connection.commit()
            return "inserted"

        if decision == "ignore_identical":
            connection.rollback()
            return "identical_ignored"

        # All other decisions refuse to modify the ledger.
        connection.rollback()

        raise ValueError(
            f"Historical reconciliation blocked: {decision}"
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
