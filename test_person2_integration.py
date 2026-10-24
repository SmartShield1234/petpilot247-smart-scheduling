
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from geographic_eligibility_adapter import GeographicEligibilityAdapter
from pavi_live_ghl_provider import (
    IntegrationUnavailable,
    LiveGHLProviders,
)
from pavi_recommendation_pipeline import Staff
from maps_service import get_driving_minutes


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
            await adapter.verify("calendar", "groomer", "address")

    async def test_rejected_territory(self):
        async def authority(*args):
            return test_staff(False)

        adapter = GeographicEligibilityAdapter(authority)

        with self.assertRaises(IntegrationUnavailable):
            await adapter.verify("calendar", "groomer", "address")

    async def test_approved_territory(self):
        async def authority(*args):
            return test_staff(True)

        adapter = GeographicEligibilityAdapter(authority)
        staff = await adapter.verify("calendar", "groomer", "address")

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)

    async def test_provider_integration(self):
        async def authority(*args):
            return test_staff(True)

        adapter = GeographicEligibilityAdapter(authority)
        provider = LiveGHLProviders(staff_authority=adapter.verify)

        staff = await provider.staff("calendar", "groomer", "address")

        self.assertTrue(staff.territory_verified)

    async def test_maps_provider_integration(self):
        async def route(origin, destination):
            return 18.0

        provider = LiveGHLProviders(routes=route)

        result = await provider.travel("Customer A", "Customer B")
        self.assertEqual(result, 18.0)


if __name__ == "__main__":
    unittest.main()
