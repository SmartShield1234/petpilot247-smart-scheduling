"""Live server-side GHL and Google Routes adapter for the Step 849 pipeline.

READ-ONLY. An independently established synchronization checkpoint and trusted
staff/territory service are REQUIRED. No client-supplied approvals are accepted.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from pavi_recommendation_pipeline import Appointment, Snapshot, Staff
from ghl_free_slot_parser import parse_ghl_free_slots
from ghl_service import get_ghl_appointments
from maps_service import get_driving_minutes


class IntegrationUnavailable(RuntimeError):
    pass


class LiveGHLProviders:
    def __init__(self, *, snapshot_authority=None, staff_authority=None,
                 routes=None, http_client=None):
        # Authorities must be server-controlled functions or authenticated
        # service clients. Do not expose their inputs as request parameters.
        self.snapshot_authority = snapshot_authority
        self.staff_authority = staff_authority
        self.routes = routes or self._google_route
        self.http_client = http_client
        self._snapshot = None

    @staticmethod
    def _calendar_ids():
        ids = [x.strip() for x in os.getenv('GHL_SCHEDULING_CALENDAR_IDS', '').split(',') if x.strip()]
        if len(ids) != 11 or len(set(ids)) != 11:
            raise IntegrationUnavailable('Complete 11-calendar inventory required')
        return ids

    async def appointments(self, calendar_id: str) -> Snapshot:
        if calendar_id not in self._calendar_ids():
            raise IntegrationUnavailable('Calendar not configured')
        if self.snapshot_authority is None:
            raise IntegrationUnavailable('Authenticated synchronization authority not configured')
        # This authority must validate checkpoint/event completeness independently.
        verified = await self.snapshot_authority()
        if verified is not True:
            raise IntegrationUnavailable('Synchronization incomplete')
        raise IntegrationUnavailable('Authenticated appointment-to-groomer mapping not yet installed')

    async def staff(self, calendar_id: str, groomer_id: str, address: str) -> Staff:
        if self.staff_authority is None:
            raise IntegrationUnavailable('Authoritative groomer territory service unavailable')
        staff = await self.staff_authority(calendar_id, groomer_id, address)
        if not isinstance(staff, Staff):
            raise IntegrationUnavailable('Invalid staff evidence')
        return staff

    async def free_starts(self, calendar_id: str, groomer_id: str,
                          preferred: datetime) -> frozenset[datetime]:
        if calendar_id not in self._calendar_ids():
            raise IntegrationUnavailable('Calendar not configured')
        if preferred.tzinfo is None:
            raise IntegrationUnavailable('Timezone-aware time required')
        token = os.getenv('GHL_API_TOKEN', '').strip()
        if not token:
            raise IntegrationUnavailable('GHL token missing')
        start = preferred.astimezone(timezone.utc) - timedelta(hours=12)
        end = start + timedelta(days=7)
        headers = {'Authorization': f'Bearer {token}',
                   'Version': os.getenv('GHL_API_VERSION', '2021-07-28'),
                   'Accept': 'application/json'}
        params = {'startDate': int(start.timestamp()*1000),
                  'endDate': int(end.timestamp()*1000),
                  'timezone': 'America/New_York', 'userId': groomer_id}
        async def fetch(client):
            response = await client.get(
                f'https://services.leadconnectorhq.com/calendars/{calendar_id}/free-slots',
                params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        if self.http_client is not None:
            data = await fetch(self.http_client)
        else:
            async with httpx.AsyncClient(timeout=25) as client:
                data = await fetch(client)
        parsed = parse_ghl_free_slots(data)
        return frozenset(x.astimezone(timezone.utc)
                         for entries in parsed['slots_by_date'].values() for x in entries)

    @staticmethod
    async def _google_route(origin: str, destination: str) -> float:
        key = os.getenv('GOOGLE_MAPS_API_KEY', '').strip()
        if not key:
            raise IntegrationUnavailable('Google Routes key missing')
        result = await get_driving_minutes(origin, destination, key)
        return float(result['driving_minutes'])

    async def travel(self, origin: str, destination: str) -> float:
        return await self.routes(origin, destination)
