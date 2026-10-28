
"""Person 2 integration tests for PetPilot247 Smart Scheduling."""

import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from geographic_eligibility_adapter import GeographicEligibilityAdapter
from geographic_staff_bridge import create_geographic_staff_authority
from pavi_live_ghl_provider import (
    IntegrationUnavailable,
    LiveGHLProviders,
)
from pavi_recommendation_pipeline import (
    Staff,
    Request,
    Snapshot,
    recommend,
)


TEST_DATE = date(2026, 10, 26)
TEST_ZONE = "America/New_York"


def test_staff(territory_verified=True):
    """Create fictional, date-specific Staff data for testing."""
    zone = ZoneInfo(TEST_ZONE)

    return Staff(
        approved=True,
        territory_verified=territory_verified,
        work_start=datetime(2026, 10, 26, 9, tzinfo=zone),
        work_end=datetime(2026, 10, 26, 17, tzinfo=zone),
        depot_address="Test Depot",
        setup_minutes=10,
        cleanup_minutes=10,
        buffer_minutes=15,
    )


class Person2IntegrationTests(unittest.IsolatedAsyncioTestCase):

    async def test_missing_authority(self):
        adapter = GeographicEligibilityAdapter()

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                TEST_DATE,
                TEST_ZONE,
            )

    async def test_rejected_territory(self):
        async def authority(*args):
            return test_staff(False)

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                TEST_DATE,
                TEST_ZONE,
            )

    async def test_naive_working_hours_rejected(self):
        async def authority(*args):
            start = datetime(2026, 10, 26, 9)

            return Staff(
                approved=True,
                territory_verified=True,
                work_start=start,
                work_end=start + timedelta(hours=8),
                depot_address="Test Depot",
                setup_minutes=10,
                cleanup_minutes=10,
                buffer_minutes=15,
            )

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                TEST_DATE,
                TEST_ZONE,
            )

    async def test_approved_territory(self):
        async def authority(*args):
            return test_staff(True)

        adapter = GeographicEligibilityAdapter(authority)

        staff = await adapter.verify(
            "calendar",
            "groomer",
            "address",
            TEST_DATE,
            TEST_ZONE,
        )

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)
        self.assertEqual(staff.work_start.date(), TEST_DATE)
        self.assertEqual(staff.work_end.date(), TEST_DATE)

    async def test_staff_bridge_integration(self):
        """Verify the five-argument Staff Bridge directly."""

        async def authority(
            calendar_id,
            groomer_id,
            address,
            appointment_date,
            timezone_name,
        ):
            self.assertEqual(calendar_id, "calendar")
            self.assertEqual(groomer_id, "groomer")
            self.assertEqual(address, "address")
            self.assertEqual(appointment_date, TEST_DATE)
            self.assertEqual(timezone_name, TEST_ZONE)

            return test_staff(True)

        staff_authority = create_geographic_staff_authority(
            authenticated_authority=authority
        )

        staff = await staff_authority(
            "calendar",
            "groomer",
            "address",
            TEST_DATE,
            TEST_ZONE,
        )

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)

    async def test_invalid_appointment_date(self):
        async def authority(*args):
            return test_staff()

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                "2026-10-26",
                TEST_ZONE,
            )

    async def test_missing_timezone(self):
        async def authority(*args):
            return test_staff()

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                TEST_DATE,
                None,
            )

    async def test_invalid_timezone(self):
        async def authority(*args):
            return test_staff()

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                TEST_DATE,
                "Invalid/Timezone",
            )

    async def test_unavailable_working_schedule(self):
        async def authority(*args):
            return None

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                TEST_DATE,
                TEST_ZONE,
            )

    async def test_mismatched_schedule_date(self):
        async def authority(*args):
            return test_staff()

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                date(2026, 10, 27),
                TEST_ZONE,
            )

    async def test_legacy_three_argument_call_blocked(self):
        async def authority(*args):
            return test_staff()

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
            )

    async def test_maps_provider_integration(self):
        async def route(origin, destination):
            return 18.0

        provider = LiveGHLProviders(routes=route)

        result = await provider.travel(
            "Customer A",
            "Customer B",
        )

        self.assertEqual(result, 18.0)

    async def test_maps_failure_blocks_recommendations(self):
        """A Maps failure must not produce bookable recommendations."""

        class FailingMapsProvider:

            async def calendar_timezone(self, calendar_id):
                return TEST_ZONE

            async def appointments(self, calendar_id):
                return Snapshot(
                    sync_verified=True,
                    complete_all_calendars=True,
                    groomer_ids=("test-groomer",),
                    appointments_by_groomer={
                        "test-groomer": (),
                    },
                )

            async def staff(
                self,
                calendar_id,
                groomer_id,
                address,
                appointment_date,
                timezone_name,
            ):
                # Date-specific fictional staff evidence.
                return test_staff(True)

            async def free_starts(
                self,
                calendar_id,
                groomer_id,
                preferred,
            ):
                return frozenset({preferred})

            async def travel(
                self,
                origin,
                destination,
            ):
                raise RuntimeError(
                    "Google Maps unavailable"
                )

        request = Request(
            calendar_id="test-calendar",
            customer_address="Test Customer",
            preferred_start=datetime(
                2026,
                10,
                26,
                11,
                tzinfo=timezone.utc,
            ),
            service_minutes=90,
        )

        result = await recommend(
            request,
            FailingMapsProvider(),
        )

        self.assertEqual(
            result["recommendations"],
            [],
        )

        self.assertFalse(
            result["booking_authorized"]
        )

        self.assertEqual(
            result["reason"],
            "Verified upstream evidence unavailable",
        )

    async def test_dst_spring_forward_nonexistent_time_rejected(self):
        zone = ZoneInfo(TEST_ZONE)

        async def authority(*args):
            return Staff(
                approved=True,
                territory_verified=True,
                work_start=datetime(
                    2026, 3, 8, 2, 30, tzinfo=zone
                ),
                work_end=datetime(
                    2026, 3, 8, 5, 0, tzinfo=zone
                ),
                depot_address="Test Depot",
                setup_minutes=10,
                cleanup_minutes=10,
                buffer_minutes=15,
            )

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                date(2026, 3, 8),
                TEST_ZONE,
            )

    async def test_dst_fall_back_ambiguous_time_rejected(self):
        zone = ZoneInfo(TEST_ZONE)

        async def authority(*args):
            return Staff(
                approved=True,
                territory_verified=True,
                work_start=datetime(
                    2026, 11, 1, 1, 30, tzinfo=zone
                ),
                work_end=datetime(
                    2026, 11, 1, 4, 0, tzinfo=zone
                ),
                depot_address="Test Depot",
                setup_minutes=10,
                cleanup_minutes=10,
                buffer_minutes=15,
            )

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                date(2026, 11, 1),
                TEST_ZONE,
            )

    async def test_dst_reversed_utc_working_hours_rejected(self):
        zone = ZoneInfo(TEST_ZONE)

        async def authority(*args):
            return Staff(
                approved=True,
                territory_verified=True,
                work_start=datetime(
                    2026, 11, 1, 1, 45,
                    tzinfo=zone,
                    fold=1,
                ),
                work_end=datetime(
                    2026, 11, 1, 1, 15,
                    tzinfo=zone,
                    fold=0,
                ),
                depot_address="Test Depot",
                setup_minutes=10,
                cleanup_minutes=10,
                buffer_minutes=15,
            )

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify(
                "calendar",
                "groomer",
                "address",
                date(2026, 11, 1),
                TEST_ZONE,
            )

    async def test_dst_transition_date_valid_hours_accepted(self):
        zone = ZoneInfo(TEST_ZONE)

        async def authority(*args):
            return Staff(
                approved=True,
                territory_verified=True,
                work_start=datetime(
                    2026, 3, 8, 9, 0, tzinfo=zone
                ),
                work_end=datetime(
                    2026, 3, 8, 17, 0, tzinfo=zone
                ),
                depot_address="Test Depot",
                setup_minutes=10,
                cleanup_minutes=10,
                buffer_minutes=15,
            )

        adapter = GeographicEligibilityAdapter(authority)

        staff = await adapter.verify(
            "calendar",
            "groomer",
            "address",
            date(2026, 3, 8),
            TEST_ZONE,
        )

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)


if __name__ == "__main__":
    unittest.main()
