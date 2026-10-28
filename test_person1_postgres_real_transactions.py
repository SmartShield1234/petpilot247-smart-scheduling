"""Isolated real-PostgreSQL tests for Person 1 guarded snapshot recovery.

Required environment (GitHub Actions disposable postgres:18 only):
  PETPILOT_TEST_DATABASE_URL=postgresql://petpilot_test:petpilot_test_only@127.0.0.1:5432/petpilot_reconciliation_test

Never point this at Render or a shared database. The hostname, database name,
username and explicit opt-in are checked before connecting.
"""
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

import psycopg
from postgres_appointment_reconciliation import apply_guarded_snapshot_recovery

CALENDARS = [f"test-calendar-{i}" for i in range(11)]
BASE = "2026-11-04T10:00:00+00:00"
END = "2026-11-04T11:00:00+00:00"
OLD = "2026-11-03T10:00:00+00:00"
NEW = "2026-11-05T10:00:00+00:00"


def row(appointment_id, revision=BASE, status="confirmed"):
    return dict(location_id="test-location", appointment_id=appointment_id,
                calendar_id=CALENDARS[0], assigned_user_id="test-groomer",
                contact_id="test-contact", appointment_status=status,
                start_time=BASE, end_time=END, date_updated=revision)


class RealPostgresReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get("PETPILOT_TEST_DATABASE_URL", "")
        parsed = urlparse(raw)
        if not (os.environ.get("PETPILOT_DB_INTEGRATION_TEST") == "1"
                and parsed.scheme in ("postgres", "postgresql")
                and parsed.hostname in ("localhost", "127.0.0.1")
                and parsed.port == 5432
                and parsed.username == "petpilot_test"
                and parsed.path == "/petpilot_reconciliation_test"
                and not parse_qs(parsed.query)):
            raise RuntimeError("Refusing non-isolated PostgreSQL connection")
        cls.url = raw
        cls.original_connect = psycopg.connect

        # GitHub Actions' disposable postgres container has no TLS.
        # The real application requires TLS; override only for this strictly
        # localhost-gated test, never in application source.
        def local_test_connect(conninfo, **kwargs):
            if conninfo != cls.url:
                raise RuntimeError("Unexpected database target")
            kwargs["sslmode"] = "disable"
            return cls.original_connect(conninfo, **kwargs)

        cls.connection_patch = patch("postgres_appointment_reconciliation.psycopg.connect", side_effect=local_test_connect)
        cls.connection_patch.start()
        cls.previous_env = {k: os.environ.get(k) for k in ("PETPILOT_ENV", "PETPILOT_LIVE_BOOKING_ENABLED")}
        os.environ["PETPILOT_ENV"] = "development"
        os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] = "false"
        with cls.original_connect(raw, sslmode="disable") as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS appointments (
                    location_id TEXT NOT NULL, appointment_id TEXT NOT NULL,
                    calendar_id TEXT, assigned_user_id TEXT, contact_id TEXT,
                    appointment_status TEXT, start_time TEXT, end_time TEXT,
                    date_updated TEXT, is_deleted INTEGER NOT NULL DEFAULT 0,
                    source TEXT, PRIMARY KEY(location_id, appointment_id))""")
                cur.execute("""CREATE TABLE IF NOT EXISTS appointment_event_log (
                    event_log_id BIGSERIAL PRIMARY KEY, location_id TEXT,
                    appointment_id TEXT, event_type TEXT, received_at TEXT,
                    event_hash TEXT)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS appointment_sync_health (
                    id INTEGER PRIMARY KEY, status TEXT NOT NULL,
                    reason TEXT, last_reconciled_at TEXT, updated_at TEXT)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS service_address_confirmations (
                    location_id TEXT, appointment_id TEXT)""")

    @classmethod
    def tearDownClass(cls):
        cls.connection_patch.stop()
        for key, value in cls.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def setUp(self):
        with self.original_connect(self.url, sslmode="disable") as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM service_address_confirmations")
                cur.execute("DELETE FROM appointment_event_log")
                cur.execute("DELETE FROM appointments")
                cur.execute("DELETE FROM appointment_sync_health")
                cur.execute("INSERT INTO appointment_sync_health (id, status) VALUES (1, 'uncertain')")

    def insert(self, item):
        with self.original_connect(self.url, sslmode="disable") as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO appointments (location_id, appointment_id, calendar_id,
                    assigned_user_id, contact_id, appointment_status, start_time, end_time,
                    date_updated, is_deleted, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'webhook')""",
                    tuple(item[key] for key in ("location_id", "appointment_id", "calendar_id",
                        "assigned_user_id", "contact_id", "appointment_status", "start_time",
                        "end_time", "date_updated")))

    def read(self, appointment_id):
        with self.original_connect(self.url, sslmode="disable") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT date_updated, appointment_status FROM appointments WHERE appointment_id=%s", (appointment_id,))
                return cur.fetchone()

    def recover(self, snapshots, **kw):
        return apply_guarded_snapshot_recovery(connection_url=self.url, snapshots=snapshots,
            expected_calendar_ids=CALENDARS, **kw)

    def test_real_insert_does_not_verify_sync_or_authorize_booking(self):
        result = self.recover([row("one")])
        self.assertEqual(result["inserted"], 1)
        self.assertFalse(result["synchronization_verified"])
        self.assertFalse(result["booking_authorized"])
        self.assertEqual(self.read("one")[0], BASE)
        with self.original_connect(self.url, sslmode="disable") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status, last_reconciled_at FROM appointment_sync_health WHERE id=1")
                self.assertEqual(cur.fetchone(), ("uncertain", None))

    def test_older_snapshot_rejected_and_current_row_unchanged(self):
        self.insert(row("one", NEW))
        with self.assertRaisesRegex(RuntimeError, "GHL snapshot older than ledger"):
            self.recover([row("one", OLD)])
        self.assertEqual(self.read("one"), (NEW, "confirmed"))

    def test_later_stale_record_rolls_back_prior_insert(self):
        self.insert(row("z-old", NEW))
        with self.assertRaisesRegex(RuntimeError, "GHL snapshot older than ledger"):
            self.recover([row("a-new"), row("z-old", OLD)])
        self.assertIsNone(self.read("a-new"))
        self.assertEqual(self.read("z-old")[0], NEW)

    def test_same_revision_conflict_rejected(self):
        self.insert(row("one"))
        with self.assertRaisesRegex(RuntimeError, "Conflicting same-revision data"):
            self.recover([row("one", BASE, status="cancelled")])
        self.assertEqual(self.read("one")[1], "confirmed")

    def test_event_checkpoint_mismatch_preserves_rows(self):
        self.insert(row("one"))
        with self.assertRaisesRegex(RuntimeError, "Webhook event log changed"):
            self.recover([row("one", NEW)], expected_event_checkpoint=(99, 99))
        self.assertEqual(self.read("one")[0], BASE)


if __name__ == "__main__":
    unittest.main()
