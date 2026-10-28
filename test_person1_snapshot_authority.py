
import asyncio
import os
from unittest.mock import patch

from pavi_live_ghl_provider import (
    LiveGHLProviders,
    IntegrationUnavailable,
)
from pavi_recommendation_pipeline import Snapshot


CALENDAR_ID = "test-calendar-01"


def make_snapshot(verified=True, complete=True):
    return Snapshot(
        sync_verified=verified,
        complete_all_calendars=complete,
        groomer_ids=("ambily",),
        appointments_by_groomer={"ambily": ()},
    )


async def run_tests():
    async def verified_sync():
        return True

    async def valid_snapshot(calendar_id):
        assert calendar_id == CALENDAR_ID
        return make_snapshot()

    async def unverified_snapshot(calendar_id):
        return make_snapshot(verified=False)

    async def incomplete_snapshot(calendar_id):
        return make_snapshot(complete=False)

    async def invalid_snapshot(calendar_id):
        return {"sync_verified": True}

    async def expect_rejected(authority, message):
        provider = LiveGHLProviders(
            snapshot_authority=verified_sync,
            appointment_snapshot_authority=authority,
        )
        try:
            await provider.appointments(CALENDAR_ID)
        except IntegrationUnavailable:
            print(message, "| PASS")
        else:
            raise AssertionError(message + " was not rejected")

    with patch.dict(
        os.environ,
        {"GHL_SCHEDULING_CALENDAR_IDS": CALENDAR_ID},
    ), patch.object(
        LiveGHLProviders,
        "_calendar_ids",
        return_value=[CALENDAR_ID],
    ):
        provider = LiveGHLProviders(
            snapshot_authority=verified_sync,
            appointment_snapshot_authority=valid_snapshot,
        )
        snapshot = await provider.appointments(CALENDAR_ID)

        assert snapshot.sync_verified is True
        assert snapshot.complete_all_calendars is True
        print("Verified snapshot accepted | PASS")

        await expect_rejected(
            unverified_snapshot,
            "Unverified snapshot rejected",
        )
        await expect_rejected(
            incomplete_snapshot,
            "Incomplete snapshot rejected",
        )
        await expect_rejected(
            invalid_snapshot,
            "Invalid snapshot type rejected",
        )
        await expect_rejected(
            None,
            "Missing snapshot authority rejected",
        )

    print("PERSON 1 SNAPSHOT AUTHORITY TEST PASSED")
    print("Fictional data only. Live booking not authorized.")


if __name__ == "__main__":
    asyncio.run(run_tests())
