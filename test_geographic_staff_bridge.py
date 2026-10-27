
"""Automated tests for the PetPilot247 geographic staff bridge."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from geographic_staff_bridge import (
    create_geographic_staff_authority,
    create_geographic_enabled_provider,
)
from pavi_live_ghl_provider import IntegrationUnavailable, LiveGHLProviders
from pavi_recommendation_pipeline import Staff


class TestGeographicStaffBridge(unittest.TestCase):

    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def make_staff(self, **overrides):
        data = {
            "approved": True,
            "territory_verified": True,
            "work_start": self.now,
            "work_end": self.now + timedelta(hours=8),
            "depot_address": "123 Fictional Depot Road, PA 19006",
            "setup_minutes": 10,
            "cleanup_minutes": 10,
            "buffer_minutes": 15,
        }
        data.update(overrides)
        return Staff(**data)

    def execute(self, authority):
        return asyncio.run(
            authority(
                "TEST_CALENDAR",
                "TEST_GROOMER",
                "123 Test Street, PA 19006",
            )
        )

    def test_missing_authority_blocked(self):
        authority = create_geographic_staff_authority()

        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_valid_fictional_staff(self):
        async def fictional_authority(calendar_id, groomer_id, address):
            return self.make_staff()

        authority = create_geographic_staff_authority(
            authenticated_authority=fictional_authority
        )

        staff = self.execute(authority)

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)

    def test_unapproved_groomer_blocked(self):
        async def fictional_authority(calendar_id, groomer_id, address):
            return self.make_staff(approved=False)

        authority = create_geographic_staff_authority(
            authenticated_authority=fictional_authority
        )

        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_unverified_territory_blocked(self):
        async def fictional_authority(calendar_id, groomer_id, address):
            return self.make_staff(territory_verified=False)

        authority = create_geographic_staff_authority(
            authenticated_authority=fictional_authority
        )

        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_invalid_working_hours_blocked(self):
        async def fictional_authority(calendar_id, groomer_id, address):
            return self.make_staff(
                work_end=self.now - timedelta(hours=1)
            )

        authority = create_geographic_staff_authority(
            authenticated_authority=fictional_authority
        )

        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_missing_depot_blocked(self):
        async def fictional_authority(calendar_id, groomer_id, address):
            return self.make_staff(depot_address="")

        authority = create_geographic_staff_authority(
            authenticated_authority=fictional_authority
        )

        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_invalid_buffer_blocked(self):
        async def fictional_authority(calendar_id, groomer_id, address):
            return self.make_staff(buffer_minutes=-5)

        authority = create_geographic_staff_authority(
            authenticated_authority=fictional_authority
        )

        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_provider_connection(self):
        provider = create_geographic_enabled_provider()

        self.assertIsInstance(provider, LiveGHLProviders)
        self.assertTrue(callable(provider.staff_authority))

        with self.assertRaises(IntegrationUnavailable):
            asyncio.run(
                provider.staff(
                    "TEST_CALENDAR",
                    "TEST_GROOMER",
                    "123 Test Street, PA 19006",
                )
            )


if __name__ == "__main__":
    unittest.main()
