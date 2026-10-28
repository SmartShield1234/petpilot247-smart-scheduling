"""Offline safety tests; no production API calls."""
import unittest
from unittest.mock import AsyncMock, patch

from ghl_calendar_timezone_authority import (
    authenticated_calendar_timezone, CalendarTimezoneUnavailable,
)


class CalendarTimezoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_authenticated_calendar(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock(return_value={
            'calendar': {'id': 'cal1', 'timezone': 'America/New_York'}})):
            self.assertEqual(await authenticated_calendar_timezone('cal1'), 'America/New_York')

    async def test_direct_calendar_representation(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock(return_value={
            'id': 'cal1', 'timeZone': 'America/Chicago'})):
            self.assertEqual(await authenticated_calendar_timezone('cal1'), 'America/Chicago')

    async def test_mismatched_id_rejected(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock(return_value={
            'calendar': {'id': 'other', 'timezone': 'America/New_York'}})):
            with self.assertRaises(CalendarTimezoneUnavailable):
                await authenticated_calendar_timezone('cal1')

    async def test_missing_zone_rejected(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock(return_value={
            'calendar': {'id': 'cal1'}})):
            with self.assertRaises(CalendarTimezoneUnavailable):
                await authenticated_calendar_timezone('cal1')

    async def test_invalid_zone_rejected(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock(return_value={
            'calendar': {'id': 'cal1', 'timezone': 'invalid'}})):
            with self.assertRaises(CalendarTimezoneUnavailable):
                await authenticated_calendar_timezone('cal1')

    async def test_failed_api_rejected(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock(side_effect=RuntimeError('failure'))):
            with self.assertRaises(CalendarTimezoneUnavailable):
                await authenticated_calendar_timezone('cal1')

    async def test_missing_id_rejected_before_api(self):
        with patch('ghl_calendar_timezone_authority.get_ghl_calendar', new=AsyncMock()) as mock:
            with self.assertRaises(CalendarTimezoneUnavailable):
                await authenticated_calendar_timezone('')
            mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
