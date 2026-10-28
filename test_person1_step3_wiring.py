"""Step 3 fail-closed integration checks; synthetic data only, no network/DB access."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
from pavi_live_ghl_provider import LiveGHLProviders, IntegrationUnavailable
from pavi_recommendation_pipeline import Request, recommend
from datetime import datetime, timezone

CALENDARS = ','.join(f'calendar-{i}' for i in range(11))

class Step3WiringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'GHL_SCHEDULING_CALENDAR_IDS': CALENDARS}, clear=False)
        self.env.start()
    async def asyncTearDown(self):
        self.env.stop()

    async def test_all_11_calendar_inventory_required(self):
        self.assertEqual(len(LiveGHLProviders._calendar_ids()), 11)
        with patch.dict(os.environ, {'GHL_SCHEDULING_CALENDAR_IDS': 'one,two'}):
            with self.assertRaises(IntegrationUnavailable):
                LiveGHLProviders._calendar_ids()

    async def test_no_sync_authority_rejected(self):
        with self.assertRaisesRegex(IntegrationUnavailable, 'synchronization authority'):
            await LiveGHLProviders().appointments('calendar-0')

    async def test_no_snapshot_authority_rejected(self):
        with self.assertRaisesRegex(IntegrationUnavailable, 'snapshot authority'):
            await LiveGHLProviders(snapshot_authority=AsyncMock(return_value=True)).appointments('calendar-0')

    async def test_no_staff_authority_rejected(self):
        with self.assertRaisesRegex(IntegrationUnavailable, 'territory service'):
            await LiveGHLProviders().staff('calendar-0', 'groomer', '123 Test St', datetime.now(timezone.utc).date(), 'America/New_York')

    async def test_no_timezone_authority_rejected(self):
        with self.assertRaisesRegex(IntegrationUnavailable, 'timezone authority'):
            await LiveGHLProviders().calendar_timezone('calendar-0')

    async def test_missing_authorities_fail_closed_at_pipeline(self):
        payload = Request('calendar-0', '123 Test Street', datetime(2026, 11, 2, 14, tzinfo=timezone.utc), 90)
        with self.assertRaises(IntegrationUnavailable):
            await recommend(payload, LiveGHLProviders())

    async def test_maps_interface_uses_mock_and_returns_minutes(self):
        from maps_service import get_driving_minutes
        with patch.dict(os.environ, {'GOOGLE_MAPS_API_KEY': 'CI_PLACEHOLDER'}):
            with patch('pavi_live_ghl_provider.get_driving_minutes', new_callable=AsyncMock) as route:
                route.return_value = {'driving_minutes': 18, 'distance_meters': 9000}
                self.assertEqual(await LiveGHLProviders().travel('A', 'B'), 18.0)
                route.assert_awaited_once_with('A', 'B', 'CI_PLACEHOLDER')

if __name__ == '__main__':
    unittest.main(verbosity=2)
