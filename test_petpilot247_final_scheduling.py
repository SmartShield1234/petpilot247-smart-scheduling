
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from petpilot247_final_scheduling_provider import (
    check_internal_scheduling_readiness,
)
from ghl_combined_scheduling_recheck import (
    combined_scheduling_recheck,
)


async def main():
    start = (
        datetime.now(timezone.utc) + timedelta(days=3)
    ).replace(hour=14, minute=0, second=0, microsecond=0)

    print("===== STEP 4.32 - STAGING INTEGRATION =====")

    # Real inventory must reject unapproved calendars.
    blocked = await check_internal_scheduling_readiness(
        calendar_id="unknown-calendar",
        groomer_id="unknown-groomer",
    )
    assert blocked["status"] == "blocked"
    assert blocked["booking_authorized"] is False
    print("Unapproved/unknown calendar rejected: PASS")

    # Trusted fictional evidence for component integration only.
    params = {
        "calendar_id": "test-calendar",
        "groomer_id": "test-groomer",
        "requested_start": start,
        "customer_address": "Fictional Customer Address",
        "service_minutes": 90,
        "availability": {
            "verification_status": "free_slots_only",
            "booking_authorized": False,
            "calendar_availability": {
                "test-groomer": {
                    "slots_by_date": {
                        start.date().isoformat(): [start]
                    }
                }
            },
        },
        "appointments": [],
        "previous_appointment": {
            "address": "Fictional Previous Address",
            "end_time": start - timedelta(minutes=45),
        },
        "next_appointment": {
            "address": "Fictional Next Address",
            "start_time": start + timedelta(minutes=150),
        },
        "maps_api_key": "mock-key",
        "evidence_verified": True,
        "evidence_fetched_at": datetime.now(timezone.utc),
    }

    routes = [
        {"driving_minutes": 20, "distance_meters": 5000},
        {"driving_minutes": 20, "distance_meters": 5000},
    ]

    with patch(
        "ghl_final_travel_validator.get_driving_minutes",
        side_effect=routes,
    ):
        passed = await combined_scheduling_recheck(**params)

    assert passed["status"] == "development_checks_passed", passed
    assert passed["booking_authorized"] is False
    print("Combined staging validation: PASS")

    stale = await combined_scheduling_recheck(
        **{
            **params,
            "evidence_fetched_at":
                datetime.now(timezone.utc) - timedelta(minutes=5),
        }
    )

    assert stale["status"] == "rejected"
    print("Stale scheduling evidence rejected: PASS")

    missing_address = await combined_scheduling_recheck(
        **{
            **params,
            "customer_address": "",
        }
    )

    assert missing_address["status"] == "rejected"
    print("Missing service address rejected: PASS")

    print("STEP 4.32 PASSED")
    print("Live booking authorized: False")


if __name__ == "__main__":
    asyncio.run(main())
