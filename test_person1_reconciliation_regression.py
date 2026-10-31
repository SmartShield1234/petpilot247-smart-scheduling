"""Deterministic, offline safety tests for guarded PostgreSQL recovery.

Run from the repository root:
    python -m unittest test_person1_reconciliation_regression -v

No real GHL, PostgreSQL, credentials, or network requests are used.
"""

import copy
import os
import sys
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


CALENDARS = [f"test-calendar-{n}" for n in range(11)]
START = "2026-11-04T10:00:00+00:00"
END = "2026-11-04T11:00:00+00:00"


def snapshot(appointment_id, revision, **overrides):
    row = {
        "location_id": "test-location",
        "appointment_id": appointment_id,
        "calendar_id": CALENDARS[0],
        "assigned_user_id": "test-groomer",
        "contact_id": "test-contact",
        "appointment_status": "confirmed",
        "start_time": START,
        "end_time": END,
        "date_updated": revision,
    }
    row.update(overrides)
    return row


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.last = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        text = str(query).strip().lower()
        if "select pg_advisory_xact_lock" in text:
            self.last = (None,)
        elif "from appointment_event_log" in text:
            self.last = (0, 0)
        elif "select status from appointment_sync_health" in text:
            self.last = (self.conn.health,)
        elif "select * from appointments" in text:
            self.last = (1,) if tuple(params) in self.conn.pending else None
        elif "select calendar_id, assigned_user_id, contact_id" in text:
            record = self.conn.pending[tuple(params)]
            self.last = tuple(record.get(k) for k in (
                "calendar_id", "assigned_user_id", "contact_id",
                "appointment_status", "start_time", "end_time",
                "date_updated", "is_deleted",
            ))
        elif "update appointments" in text:
            row = self.conn.pending[tuple(params[-2:])]
            keys = ("calendar_id", "assigned_user_id", "contact_id",
                    "appointment_status", "start_time", "end_time", "date_updated")
            row.update(dict(zip(keys, params[:7])))
            self.conn.updates += 1
        elif "delete from service_address_confirmations" in text:
            self.conn.deletes += 1
        elif "update appointment_sync_health" in text:
            self.conn.health = "uncertain"
        elif "insert into appointments" in text:
            columns = (
                "location_id", "appointment_id", "calendar_id",
                "assigned_user_id", "contact_id", "appointment_status",
                "start_time", "end_time", "date_updated", "is_deleted", "source",
            )
            row = dict(zip(columns, params))
            identity = (row["location_id"], row["appointment_id"])
            if identity in self.conn.pending:
                raise AssertionError("Duplicate insert")
            self.conn.pending[identity] = row
            self.conn.inserts += 1
        else:
            raise AssertionError(f"Unexpected SQL in offline fake: {str(query)[:100]}")
        return self

    def fetchone(self):
        return self.last


class FakeConnection:
    def __init__(self, rows):
        self.persisted = copy.deepcopy(rows)
        self.pending = None
        self.health = "uncertain"
        self.inserts = 0
        self.updates = 0
        self.deletes = 0
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        self.pending = copy.deepcopy(self.persisted)
        try:
            yield self
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.persisted = self.pending
            self.commits += 1
        finally:
            self.pending = None


def load_source():
    """Load the repository module with outbound dependencies replaced by stubs."""
    module_name = "person1_reconciliation_isolated_test_target"
    package_stubs = {
        "psycopg": types.ModuleType("psycopg"),
        "psycopg.sql": types.ModuleType("psycopg.sql"),
        "ghl_service": types.ModuleType("ghl_service"),
        "ghl_historical_snapshot_adapter": types.ModuleType("ghl_historical_snapshot_adapter"),
        "postgres_appointment_events": types.ModuleType("postgres_appointment_events"),
    }
    class FakeSQL:
        def __init__(self, value):
            self.value = str(value)

        def __str__(self):
            return self.value

        def format(self, *args):
            return FakeSQL(self.value.format(*(str(a) for a in args)))

        def join(self, items):
            return FakeSQL(self.value.join(str(x) for x in items))

    sql_stub = package_stubs["psycopg.sql"]
    sql_stub.SQL = FakeSQL
    sql_stub.Identifier = lambda name: FakeSQL(name)
    sql_stub.Placeholder = lambda: FakeSQL("%s")

    package_stubs["psycopg"].sql = sql_stub
    package_stubs["psycopg"].connect = lambda *args, **kwargs: None
    package_stubs["ghl_service"].get_ghl_appointments = lambda **kw: None
    package_stubs["ghl_historical_snapshot_adapter"].map_ghl_historical_snapshot = lambda event: event
    package_stubs["postgres_appointment_events"].mark_postgres_sync_uncertain = lambda **kw: None
    path = Path(__file__).resolve().with_name("postgres_appointment_reconciliation.py")
    if not path.is_file():
        raise AssertionError(f"Source file not found: {path}")
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, package_stubs):
        spec.loader.exec_module(module)
    return module


class GuardedRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = load_source()

    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "PETPILOT_ENV": "development",
            "PETPILOT_LIVE_BOOKING_ENABLED": "false",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_recovery(self, conn, snapshots):
        with patch.dict(sys.modules, {"psycopg": self.target.psycopg, "psycopg.sql": self.target.psycopg.sql}), patch.object(self.target.psycopg, "connect", return_value=conn):
            return self.target.apply_guarded_snapshot_recovery(
                connection_url="offline-test-database",
                snapshots=snapshots,
                expected_calendar_ids=CALENDARS,
                trusted_recovery=True,
                expected_event_checkpoint=(0, 0),
            )

    @staticmethod
    def existing(snap):
        return {(snap["location_id"], snap["appointment_id"]): {**snap, "is_deleted": 0}}

    def test_older_snapshot_rejected_without_writing(self):
        current = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        older = snapshot("appointment-a", "2026-11-04T11:00:00+00:00")
        conn = FakeConnection(self.existing(current))
        with self.assertRaisesRegex(RuntimeError, "GHL snapshot older than ledger"):
            self.run_recovery(conn, [older])
        self.assertEqual(conn.persisted[("test-location", "appointment-a")], {**current, "is_deleted": 0})
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.commits, 0)

    def test_same_revision_conflicting_data_rejected(self):
        original = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        changed = snapshot("appointment-a", "2026-11-04T12:00:00+00:00", appointment_status="cancelled")
        conn = FakeConnection(self.existing(original))
        with self.assertRaisesRegex(RuntimeError, "Conflicting same-revision data"):
            self.run_recovery(conn, [changed])
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.persisted[("test-location", "appointment-a")]["appointment_status"], "confirmed")

    def test_identical_snapshot_is_safe_and_booking_stays_off(self):
        original = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        conn = FakeConnection(self.existing(original))
        result = self.run_recovery(conn, [original])
        self.assertEqual(result["identical"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertIs(result["synchronization_verified"], False)
        self.assertIs(result["booking_authorized"], False)
        self.assertEqual(conn.commits, 1)

    def test_newer_snapshot_updates_but_never_authorizes_booking(self):
        old = snapshot("appointment-a", "2026-11-04T11:00:00+00:00")
        new = snapshot("appointment-a", "2026-11-04T12:00:00+00:00", appointment_status="rescheduled")
        conn = FakeConnection(self.existing(old))
        result = self.run_recovery(conn, [new])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(conn.persisted[("test-location", "appointment-a")]["appointment_status"], "rescheduled")
        self.assertFalse(result["booking_authorized"])
        self.assertFalse(result["synchronization_verified"])

    def test_transaction_rolls_back_prior_update_if_later_snapshot_is_stale(self):
        old_a = snapshot("appointment-a", "2026-11-04T11:00:00+00:00")
        newer_a = snapshot("appointment-a", "2026-11-04T12:00:00+00:00", appointment_status="rescheduled")
        current_b = snapshot("appointment-b", "2026-11-04T12:00:00+00:00")
        older_b = snapshot("appointment-b", "2026-11-04T11:00:00+00:00")
        records = {**self.existing(old_a), **self.existing(current_b)}
        conn = FakeConnection(records)
        with self.assertRaisesRegex(RuntimeError, "GHL snapshot older than ledger"):
            self.run_recovery(conn, [newer_a, older_b])
        self.assertGreaterEqual(conn.updates, 1)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.persisted, records)


if __name__ == "__main__":
    unittest.main(verbosity=2)
