
import asyncio
import os
from unittest.mock import patch

from postgres_appointment_reconciliation import (
    recover_from_verified_ghl_snapshot,
)


async def main():
    os.environ["PETPILOT_ENV"] = "development"
    os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] = "false"

    print("===== PERSON 1 - STEP 6.9 =====")

    # Invalid calendar coverage must be rejected
    # before any database connection.
    with patch(
        "postgres_appointment_reconciliation.psycopg.connect"
    ) as database_mock:
        try:
            await recover_from_verified_ghl_snapshot(
                connection_url="fictional-database",
                range_start="2026-10-26T00:00:00Z",
                range_end="2026-10-27T00:00:00Z",
                expected_calendar_ids=[
                    "fictional-calendar-1"
                ],
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Incomplete calendar coverage was accepted"
            )

        database_mock.assert_not_called()

    print("Incomplete calendar coverage rejected: PASS")
    print("PostgreSQL connection not attempted: PASS")

    # Verify that the booking safety flag remains disabled.
    assert os.environ["PETPILOT_LIVE_BOOKING_ENABLED"] == "false"

    print("Live booking authorized: False")
    print("STEP 6.9 PASSED")


if __name__ == "__main__":
    asyncio.run(main())
