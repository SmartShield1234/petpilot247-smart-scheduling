
import unittest
from datetime import datetime, timedelta, timezone

from geographic_eligibility_adapter import GeographicEligibilityAdapter
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


def test_staff(territory_verified=True):
    start = datetime.now(timezone.utc)

    return Staff(
        approved=True,
        territory_verified=territory_verified,
        work_start=start,
        work_end=start + timedelta(hours=8),
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
            )

    async def test_approved_territory(self):
        async def authority(*args):
            return test_staff(True)

        adapter = GeographicEligibilityAdapter(authority)

        staff = await adapter.verify(
            "calendar",
            "groomer",
            "address",
        )

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)

    async def test_provider_integration(self):
        async def authority(*args):
            return test_staff(True)

        adapter = GeographicEligibilityAdapter(authority)

        provider = LiveGHLProviders(
            staff_authority=adapter.verify
        )

        staff = await provider.staff(
            "calendar",
            "groomer",
            "address",
        )

        self.assertTrue(staff.territory_verified)

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
        class FailingMapsProvider:

            async def appointments(self, calendar_id):
                return Snapshot(
                    sync_verified=True,
                    complete_all_calendars=True,
                    groomer_ids=("test-groomer",),
                    appointments_by_groomer={
                        "test-groomer": ()
                    },
                )

            async def staff(
                self,
                calendar_id,
                groomer_id,
                address,
            ):
                start = datetime(
                    2026,
                    10,
                    26,
                    9,
                    tzinfo=timezone.utc,
                )

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


if __name__ == "__main__":
    unittest.main()
