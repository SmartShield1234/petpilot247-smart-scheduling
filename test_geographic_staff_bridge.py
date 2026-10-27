
"""Tests for the date-specific geographic staff bridge."""

import asyncio
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from geographic_staff_bridge import (
    create_geographic_staff_authority,
    create_geographic_enabled_provider,
)
from pavi_live_ghl_provider import IntegrationUnavailable, LiveGHLProviders
from pavi_recommendation_pipeline import Staff


TEST_DATE = date(2026, 10, 26)
TEST_ZONE = "America/New_York"


class TestGeographicStaffBridge(unittest.TestCase):

    def make_staff(self, **overrides):
        zone = ZoneInfo(TEST_ZONE)
        data = {
            "approved": True,
            "territory_verified": True,
            "work_start": datetime(2026, 10, 26, 9, tzinfo=zone),
            "work_end": datetime(2026, 10, 26, 17, tzinfo=zone),
            "depot_address": "123 Fictional Depot Road, PA 19006",
            "setup_minutes": 10,
            "cleanup_minutes": 10,
            "buffer_minutes": 15,
        }
        data.update(overrides)
        return Staff(**data)

    def execute(
        self,
        authority,
        appointment_date=TEST_DATE,
        timezone_name=TEST_ZONE,
    ):
        return asyncio.run(
            authority(
                "TEST_CALENDAR",
                "TEST_GROOMER",
                "123 Test Street, PA 19006",
                appointment_date,
                timezone_name,
            )
        )

    def test_missing_authority_blocked(self):
        authority = create_geographic_staff_authority()
        with self.assertRaises(IntegrationUnavailable):
            self.execute(authority)

    def test_valid_fictional_staff(self):
        async def source(*args):
            return self.make_staff()

        authority = create_geographic_staff_authority(source)
        staff = self.execute(authority)

        self.assertTrue(staff.approved)
        self.assertTrue(staff.territory_verified)

    def test_unapproved_groomer_blocked(self):
        async def source(*args):
            return self.make_staff(approved=False)

        with self.assertRaises(IntegrationUnavailable):
            self.execute(create_geographic_staff_authority(source))

    def test_unverified_territory_blocked(self):
        async def source(*args):
            return self.make_staff(territory_verified=False)

        with self.assertRaises(IntegrationUnavailable):
            self.execute(create_geographic_staff_authority(source))

    def test_invalid_working_hours_blocked(self):
        async def source(*args):
            return self.make_staff(
                work_end=datetime(
                    2026, 10, 26, 8,
                    tzinfo=ZoneInfo(TEST_ZONE),
                )
            )

        with self.assertRaises(IntegrationUnavailable):
            self.execute(create_geographic_staff_authority(source))

    def test_missing_depot_blocked(self):
        async def source(*args):
            return self.make_staff(depot_address="")

        with self.assertRaises(IntegrationUnavailable):
            self.execute(create_geographic_staff_authority(source))

    def test_invalid_buffer_blocked(self):
        async def source(*args):
            return self.make_staff(buffer_minutes=-5)

        with self.assertRaises(IntegrationUnavailable):
            self.execute(create_geographic_staff_authority(source))

    def test_invalid_date_blocked(self):
        async def source(*args):
            return self.make_staff()

        with self.assertRaises(IntegrationUnavailable):
            self.execute(
                create_geographic_staff_authority(source),
                appointment_date="2026-10-26",
            )

    def test_missing_timezone_blocked(self):
        async def source(*args):
            return self.make_staff()

        with self.assertRaises(IntegrationUnavailable):
            self.execute(
                create_geographic_staff_authority(source),
                timezone_name=None,
            )

    def test_wrong_schedule_date_blocked(self):
        async def source(*args):
            return self.make_staff()

        with self.assertRaises(IntegrationUnavailable):
            self.execute(
                create_geographic_staff_authority(source),
                appointment_date=date(2026, 10, 27),
            )

    def test_legacy_three_arguments_blocked(self):
        async def source(*args):
            return self.make_staff()

        authority = create_geographic_staff_authority(source)

        with self.assertRaises(IntegrationUnavailable):
            asyncio.run(
                authority(
                    "TEST_CALENDAR",
                    "TEST_GROOMER",
                    "123 Test Street, PA 19006",
                )
            )

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
