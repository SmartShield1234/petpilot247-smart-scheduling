
import os
from unittest.mock import patch

from postgres_appointment_reconciliation import (
    apply_guarded_snapshot_recovery,
)

os.environ["PETPILOT_ENV"] = "production"
os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] = "false"

calendars = [f"test-calendar-{i}" for i in range(11)]


def expect_rejected(label, **kwargs):
    with patch(
        "postgres_appointment_reconciliation.psycopg.connect"
    ) as db:
        try:
            apply_guarded_snapshot_recovery(
                connection_url="fictional-database",
                snapshots=[],
                expected_calendar_ids=calendars,
                **kwargs,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(label + " was accepted")

        db.assert_not_called()

    print(label + ": PASS")


print("===== PERSON 1 - STEP 6.10 =====")

expect_rejected(
    "Untrusted production recovery rejected",
    trusted_recovery=False,
    expected_event_checkpoint=(0, 0),
)

expect_rejected(
    "Missing event checkpoint rejected",
    trusted_recovery=True,
    expected_event_checkpoint=None,
)

os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] = "true"

expect_rejected(
    "Recovery blocked when live booking enabled",
    trusted_recovery=True,
    expected_event_checkpoint=(0, 0),
)

print("Database connections: None")
print("STEP 6.10 PASSED")
