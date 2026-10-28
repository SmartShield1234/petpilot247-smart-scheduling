"""No external DB or customer data: mocked read-only PostgreSQL tests."""
import os
import unittest
from unittest.mock import patch
import sys
import types
try:
    import psycopg
except ImportError:
    sys.modules["psycopg"] = types.SimpleNamespace(connect=lambda *a, **k: None)
from datetime import datetime, timezone, timedelta
from pavi_postgres_sync_authority import verified_postgres_sync, SyncEvidenceUnavailable

IDS = [f'cal-{i}' for i in range(11)]
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)

class FakeCursor:
    def __init__(self, row): self.row = row
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, q):
        assert 'SELECT' in q.upper() and 'appointment_sync_health' in q
    def fetchone(self): return self.row

class FakeConn:
    def __init__(self, row): self.row = row
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return FakeCursor(self.row)

class SyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'GHL_SCHEDULING_CALENDAR_IDS': ','.join(IDS),
            'PETPILOT_LIVE_BOOKING_ENABLED': 'false',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
    async def call(self, row, covered=IDS, **kwargs):
        async def coverage(): return covered
        with patch('pavi_postgres_sync_authority.psycopg.connect', return_value=FakeConn(row)):
            return await verified_postgres_sync(connection_url='fake-test-url', coverage_authority=coverage, now=NOW, **kwargs)
    async def test_recent_verified_full_coverage(self):
        self.assertTrue(await self.call(('verified', NOW - timedelta(minutes=3))))
    async def test_uncertain_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('uncertain', NOW))
    async def test_missing_health_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(None)
    async def test_missing_timestamp_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', None))
    async def test_stale_checkpoint_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW - timedelta(hours=2)))
    async def test_future_checkpoint_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW + timedelta(seconds=2)))
    async def test_incomplete_coverage_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW), IDS[:-1])
    async def test_wrong_coverage_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW), IDS[:-1] + ['other'])
    async def test_missing_coverage_authority_blocks(self):
        with self.assertRaises(SyncEvidenceUnavailable):
            await verified_postgres_sync(connection_url='fake', coverage_authority=None, now=NOW)
    async def test_live_booking_enabled_blocks(self):
        os.environ['PETPILOT_LIVE_BOOKING_ENABLED'] = 'true'
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW))
    async def test_duplicated_config_blocks(self):
        os.environ['GHL_SCHEDULING_CALENDAR_IDS'] = ','.join(IDS[:-1] + IDS[-2:-1])
        with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW))
    async def test_not_connected_if_preflight_fails(self):
        os.environ['PETPILOT_LIVE_BOOKING_ENABLED'] = 'true'
        with patch('pavi_postgres_sync_authority.psycopg.connect') as connect:
            with self.assertRaises(SyncEvidenceUnavailable): await self.call(('verified', NOW))
            connect.assert_not_called()

if __name__ == '__main__': unittest.main()
