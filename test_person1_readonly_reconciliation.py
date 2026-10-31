import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from test_person1_reconciliation_regression import (
    CALENDARS, snapshot, load_source,
)

START = datetime(2026, 11, 4, 9, tzinfo=timezone.utc)
END = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


class ReadOnlyConnection:
    def __init__(self, records):
        self.records = records
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, query, params=None):
        statement = str(query).strip().lower()
        if not statement.startswith("select"):
            raise AssertionError("Read-only reconciliation attempted a write")
        self.queries.append(statement)

    def fetchall(self):
        keys = (
            "location_id", "appointment_id", "calendar_id",
            "assigned_user_id", "contact_id", "appointment_status",
            "start_time", "end_time", "date_updated", "is_deleted",
        )
        return [tuple(row.get(key, 0) for key in keys)
                for row in self.records]


class ReadOnlyReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = load_source()

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PETPILOT_ENV": "development",
            "PETPILOT_LIVE_BOOKING_ENABLED": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def check(self, incoming, stored, calendars=None):
        conn = ReadOnlyConnection(stored)
        marked = []

        with patch.object(
            self.target.psycopg, "connect", return_value=conn
        ), patch.object(
            self.target, "get_ghl_appointments",
            return_value={
                "checked_calendar_ids": CALENDARS if calendars is None else calendars,
                "events": incoming,
            }
        ), patch.object(
            self.target, "map_ghl_historical_snapshot",
            side_effect=lambda event: event
        ), patch.object(
            self.target, "mark_postgres_sync_uncertain",
            side_effect=lambda **kw: marked.append(kw)
        ):
            result = asyncio.run(
                self.target.reconcile_postgres_appointments(
                    connection_url="offline-test-database",
                    range_start=START,
                    range_end=END,
                    expected_calendar_ids=CALENDARS,
                )
            )

        return result, conn, marked

    def test_identical_records_match_without_booking_approval(self):
        item = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        result, conn, marked = self.check(
            [item], [{**item, "is_deleted": 0}]
        )
        self.assertTrue(result["reconciliation_matches"])
        self.assertFalse(result["booking_authorized"])
        self.assertFalse(result["synchronization_verified"])
        self.assertEqual(len(conn.queries), 1)
        self.assertEqual(marked, [])

    def test_missing_local_appointment_detected(self):
        item = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        result, _, marked = self.check([item], [])
        self.assertEqual(result["missing_locally"], 1)
        self.assertFalse(result["reconciliation_matches"])
        self.assertTrue(marked)

    def test_changed_appointment_detected(self):
        current = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        changed = snapshot(
            "appointment-a", "2026-11-04T13:00:00+00:00",
            appointment_status="rescheduled",
        )
        result, _, marked = self.check(
            [changed], [{**current, "is_deleted": 0}]
        )
        self.assertEqual(result["changed_records"], 1)
        self.assertTrue(marked)

    def test_deleted_conflict_detected(self):
        item = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        result, _, marked = self.check(
            [item], [{**item, "is_deleted": 1}]
        )
        self.assertEqual(result["deleted_conflicts"], 1)
        self.assertFalse(result["reconciliation_matches"])
        self.assertTrue(marked)

    def test_incomplete_calendar_coverage_rejected(self):
        with self.assertRaisesRegex(
            RuntimeError, "Incomplete calendar coverage"
        ):
            self.check([], [], calendars=CALENDARS[:-1])


    def test_local_appointment_no_longer_returned_by_ghl(self):
        item = snapshot("appointment-a", "2026-11-04T12:00:00+00:00")
        result, conn, marked = self.check(
            [], [{**item, "is_deleted": 0}]
        )
        self.assertEqual(result["no_longer_returned"], 1)
        self.assertFalse(result["reconciliation_matches"])
        self.assertFalse(result["booking_authorized"])
        self.assertTrue(marked)
        self.assertEqual(len(conn.queries), 1)


if __name__ == "__main__":
    unittest.main()
