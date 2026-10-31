import unittest
from unittest.mock import patch
import os

from test_person1_reconciliation_regression import (
    FakeConnection,
    snapshot,
    CALENDARS,
    load_source,
)


class InsertOnlyRecoveryTests(unittest.TestCase):

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

    def run_recovery(self, conn, snapshots, checkpoint=(0, 0)):
        with patch.dict(
            __import__("sys").modules,
            {
                "psycopg": self.target.psycopg,
                "psycopg.sql": self.target.psycopg.sql,
            },
        ), patch.object(
            self.target.psycopg,
            "connect",
            return_value=conn,
        ):
            return self.target.apply_guarded_snapshot_recovery(
                connection_url="offline-test-database",
                snapshots=snapshots,
                expected_calendar_ids=CALENDARS,
                trusted_recovery=True,
                expected_event_checkpoint=checkpoint,
            )

    def test_existing_record_is_skipped_without_modification(self):
        original = snapshot(
            "appointment-a",
            "2026-11-04T12:00:00+00:00",
        )
        changed = snapshot(
            "appointment-a",
            "2026-11-04T13:00:00+00:00",
            appointment_status="rescheduled",
        )

        identity = ("test-location", "appointment-a")
        conn = FakeConnection({
            identity: {**original, "is_deleted": 0}
        })

        result = self.run_recovery(conn, [changed])

        self.assertEqual(result["existing_records_skipped"], 1)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(
            conn.persisted[identity]["appointment_status"],
            "confirmed",
        )
        self.assertFalse(result["synchronization_verified"])
        self.assertFalse(result["booking_authorized"])

    def test_checkpoint_mismatch_blocks_recovery(self):
        original = snapshot(
            "appointment-a",
            "2026-11-04T12:00:00+00:00",
        )

        conn = FakeConnection({})

        with self.assertRaisesRegex(
            RuntimeError,
            "Webhook event log changed",
        ):
            self.run_recovery(
                conn,
                [original],
                checkpoint=(1, 1),
            )

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.persisted, {})

    def test_live_booking_enabled_blocks_recovery(self):
        original = snapshot(
            "appointment-a",
            "2026-11-04T12:00:00+00:00",
        )

        conn = FakeConnection({})

        with patch.dict(
            os.environ,
            {"PETPILOT_LIVE_BOOKING_ENABLED": "true"},
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Live booking must remain disabled",
            ):
                self.run_recovery(conn, [original])

        self.assertEqual(conn.commits, 0)


    def test_new_appointment_inserted_without_authorizing_booking(self):
        new = snapshot(
            "appointment-new",
            "2026-11-04T12:00:00+00:00",
        )

        conn = FakeConnection({})
        result = self.run_recovery(conn, [new])

        identity = ("test-location", "appointment-new")

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["existing_records_skipped"], 0)
        self.assertEqual(conn.inserts, 1)
        self.assertIn(identity, conn.persisted)
        self.assertEqual(conn.persisted[identity]["source"], "api_reconciliation")
        self.assertEqual(conn.persisted[identity]["is_deleted"], 0)
        self.assertEqual(conn.commits, 1)
        self.assertFalse(result["synchronization_verified"])
        self.assertFalse(result["booking_authorized"])


    def test_insert_failure_rolls_back_entire_transaction(self):
        first = snapshot(
            "appointment-a",
            "2026-11-04T12:00:00+00:00",
        )
        second = snapshot(
            "appointment-b",
            "2026-11-04T12:00:00+00:00",
        )

        conn = FakeConnection({})
        original_cursor = conn.cursor

        def failing_cursor():
            cursor = original_cursor()
            original_execute = cursor.execute

            def execute(query, params=None):
                if "insert into appointments" in str(query).lower():
                    if conn.inserts >= 1:
                        raise RuntimeError("Simulated database insert failure")
                return original_execute(query, params)

            cursor.execute = execute
            return cursor

        conn.cursor = failing_cursor

        with self.assertRaisesRegex(
            RuntimeError,
            "Simulated database insert failure",
        ):
            self.run_recovery(conn, [first, second])

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.persisted, {})


if __name__ == "__main__":
    unittest.main()
