
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from appointment_ledger import DATABASE_PATH


def initialize_sync_health(db_path=DATABASE_PATH):
    """
    Create synchronization health metadata.

    New databases start in an unsafe state.
    This function never marks the ledger as synchronized.
    """

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS appointment_sync_health (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT NOT NULL DEFAULT 'unverified',
                reason TEXT NOT NULL DEFAULT 'Initial reconciliation required',
                last_reconciled_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)

        now = datetime.now(timezone.utc).isoformat()

        connection.execute(
            """
            INSERT OR IGNORE INTO appointment_sync_health (
                id, status, reason, updated_at
            )
            VALUES (1, 'unverified', ?, ?)
            """,
            ("Initial reconciliation required", now),
        )

        connection.commit()


def get_sync_health(db_path=DATABASE_PATH):
    """Read synchronization state without changing it."""

    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT status, reason, last_reconciled_at, updated_at
            FROM appointment_sync_health
            WHERE id = 1
            """
        ).fetchone()

    if row is None:
        raise ValueError("Synchronization health is not initialized")

    return {
        "status": row[0],
        "reason": row[1],
        "last_reconciled_at": row[2],
        "updated_at": row[3],
    }


def mark_sync_uncertain(reason, db_path=DATABASE_PATH):
    """
    Mark appointment synchronization as uncertain.

    This is a fail-closed state.
    """

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Synchronization failure reason required")

    now = datetime.now(timezone.utc).isoformat()

    with closing(sqlite3.connect(db_path)) as connection:
        cursor = connection.execute(
            """
            UPDATE appointment_sync_health
            SET status = 'uncertain',
                reason = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (reason.strip(), now),
        )

        if cursor.rowcount != 1:
            raise ValueError("Synchronization health is not initialized")

        connection.commit()

    return "uncertain"


def require_verified_sync(db_path=DATABASE_PATH):
    """
    Refuse to trust synchronization without a verified state.

    No automatic promotion to verified.
    """

    health = get_sync_health(db_path)

    if health["status"] != "verified":
        raise ValueError("Appointment synchronization is not verified")

    if not health["last_reconciled_at"]:
        raise ValueError("No completed reconciliation recorded")

    return True
