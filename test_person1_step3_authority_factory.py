"""Person 1 Step 3 factory and positive-path tests, all fake data, no live API."""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from pavi_provider_factory import build_live_providers
from pavi_live_ghl_provider import IntegrationUnavailable
from pavi_recommendation_pipeline import Request, Snapshot, Staff, recommend
from pavi_recommendation_router import RecommendationInput, internal_recommendations


START = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
CALENDARS = ','.join('calendar-'+str(i) for i in range(11))


class Step3IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p = patch.dict(os.environ, {'GHL_SCHEDULING_CALENDAR_IDS': CALENDARS,
                                       'PETPILOT_RECONCILIATION_API_KEY': 'test-only-secret'}, clear=False)
        self.p.start()

    async def asyncTearDown(self):
        self.p.stop()

    def callbacks(self, *, synchronized=True, approved=True, territory=True,
                  complete=True, tz='UTC', route=7):
        return dict(
            snapshot_authority=AsyncMock(return_value=synchronized),
            appointment_snapshot_authority=AsyncMock(return_value=Snapshot(
                sync_verified=synchronized, complete_all_calendars=complete,
                groomer_ids=('groomer-1',), appointments_by_groomer={'groomer-1': ()})),
            staff_authority=AsyncMock(return_value=Staff(
                approved=approved, territory_verified=territory,
                work_start=START-timedelta(hours=2), work_end=START+timedelta(hours=8),
                depot_address='123 Example St', setup_minutes=0,
                cleanup_minutes=0, buffer_minutes=0)),
            calendar_timezone_authority=AsyncMock(return_value=tz),
            routes=AsyncMock(return_value=route),
        )

    async def test_unconfigured_factory_rejects_all_missing(self):
        with self.assertRaisesRegex(IntegrationUnavailable, 'snapshot_authority'):
            build_live_providers()

    async def test_valid_synthetic_evidence_yields_nonbookable_recommendation(self):
        cb = self.callbacks()
        provider = build_live_providers(**cb)
        provider.free_starts = AsyncMock(return_value=frozenset({START}))
        result = await recommend(Request('calendar-0', '321 Customer Rd', START, 60), provider)
        self.assertEqual(len(result['recommendations']), 1)
        self.assertFalse(result['booking_authorized'])
        self.assertFalse(result['recommendations'][0]['booking_authorized'])
        cb['staff_authority'].assert_awaited_once_with('calendar-0','groomer-1','321 Customer Rd',date(2026,11,2),'UTC')

    async def test_unverified_sync_blocks(self):
        cb = self.callbacks(synchronized=False)
        provider = build_live_providers(**cb)
        result = await recommend(Request('calendar-0','321 Customer Rd', START,60),provider)
        self.assertFalse(result['recommendations'])
        self.assertFalse(result['booking_authorized'])

    async def test_missing_calendar_coverage_blocks(self):
        provider = build_live_providers(**self.callbacks(complete=False))
        result = await recommend(Request('calendar-0','321 Customer Rd', START,60),provider)
        self.assertEqual(result['recommendations'],[])

    async def test_unapproved_staff_blocks(self):
        cb=self.callbacks(approved=False)
        provider=build_live_providers(**cb)
        provider.free_starts=AsyncMock(return_value=frozenset({START}))
        result=await recommend(Request('calendar-0','321 Customer Rd',START,60),provider)
        self.assertEqual(result['recommendations'],[])

    async def test_unverified_territory_blocks(self):
        cb=self.callbacks(territory=False)
        provider=build_live_providers(**cb)
        provider.free_starts=AsyncMock(return_value=frozenset({START}))
        result=await recommend(Request('calendar-0','321 Customer Rd',START,60),provider)
        self.assertEqual(result['recommendations'],[])

    async def test_route_failure_blocks(self):
        cb=self.callbacks()
        cb['routes'].side_effect=RuntimeError('Maps unavailable')
        provider=build_live_providers(**cb)
        provider.free_starts=AsyncMock(return_value=frozenset({START}))
        result=await recommend(Request('calendar-0','321 Customer Rd',START,60),provider)
        self.assertEqual(result['recommendations'],[])

    async def test_unconfigured_internal_endpoint_returns_503(self):
        body=RecommendationInput(calendar_id='calendar-0',customer_address='321 Customer Rd',
                                 preferred_start=START,service_minutes=60)
        with self.assertRaises(HTTPException) as e:
            await internal_recommendations(body,x_reconciliation_key='test-only-secret')
        self.assertEqual(e.exception.status_code,503)

    async def test_invalid_key_returns_401(self):
        body=RecommendationInput(calendar_id='calendar-0',customer_address='321 Customer Rd',
                                 preferred_start=START,service_minutes=60)
        with self.assertRaises(HTTPException) as e:
            await internal_recommendations(body,x_reconciliation_key='wrong')
        self.assertEqual(e.exception.status_code,401)

if __name__ == '__main__':
    unittest.main()
