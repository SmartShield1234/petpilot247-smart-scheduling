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
    def __init__(
        self,
        *,
        snapshot_authority=None,
        appointment_snapshot_authority=None,
        staff_authority=None,
        calendar_timezone_authority=None,
        routes=None,
        http_client=None,
    ):
        self.snapshot_authority = snapshot_authority
        self.appointment_snapshot_authority = appointment_snapshot_authority
        self.staff_authority = staff_authority
        self.calendar_timezone_authority = calendar_timezone_authority
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
            raise IntegrationUnavailable("Calendar not configured")

        if self.snapshot_authority is None:
            raise IntegrationUnavailable(
                "Authenticated synchronization authority not configured"
            )

        verified = await self.snapshot_authority()
        if verified is not True:
            raise IntegrationUnavailable("Synchronization incomplete")

        if self.appointment_snapshot_authority is None:
            raise IntegrationUnavailable(
                "Authenticated appointment snapshot authority not configured"
            )

        snapshot = await self.appointment_snapshot_authority(calendar_id)

        if not isinstance(snapshot, Snapshot):
            raise IntegrationUnavailable("Invalid appointment snapshot")

        if (
            snapshot.sync_verified is not True
            or snapshot.complete_all_calendars is not True
        ):
            raise IntegrationUnavailable(
                "Appointment snapshot verification incomplete"
            )

        if not snapshot.groomer_ids:
            raise IntegrationUnavailable(
                "Verified groomer inventory unavailable"
            )

        if set(snapshot.appointments_by_groomer) != set(snapshot.groomer_ids):
            raise IntegrationUnavailable(
                "Appointment-to-groomer coverage incomplete"
            )

        return snapshot


   
    async def staff(
        self,
        calendar_id: str,
        groomer_id: str,
        address: str,
        appointment_date,
        timezone_name: str,
    ) -> Staff:
        if self.staff_authority is None:
            raise IntegrationUnavailable(
                "Authoritative groomer territory service unavailable"
            )

        staff = await self.staff_authority(
            calendar_id,
            groomer_id,
            address,
            appointment_date,
            timezone_name,
        )

    if not isinstance(staff, Staff):
        raise IntegrationUnavailable("Invalid staff evidence")

    if staff.approved is not True or staff.territory_verified is not True:
        raise IntegrationUnavailable("Staff authority not verified")

            if (
            staff.work_start.tzinfo is None
            or staff.work_end.tzinfo is None
            or staff.work_start.utcoffset() is None
            or staff.work_end.utcoffset() is None
            or staff.work_end <= staff.work_start
        ):
            raise IntegrationUnavailable("Invalid verified working hours")

        return staff

    async def calendar_timezone(self, calendar_id: str) -> str:

async def calendar_timezone(self, calendar_id: str) -> str:
    if calendar_id not in self._calendar_ids():
        raise IntegrationUnavailable("Calendar not configured")

    if self.calendar_timezone_authority is None:
        raise IntegrationUnavailable(
            "Authenticated calendar timezone authority not configured"
        )

    timezone_name = await self.calendar_timezone_authority(calendar_id)

    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise IntegrationUnavailable("Verified calendar timezone unavailable")

    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise IntegrationUnavailable("Invalid calendar timezone") from exc

    return timezone_name

    async def free_starts(
        self,
        calendar_id: str,
        groomer_id: str,
        preferred: datetime,
    ) -> frozenset[datetime]:
        timezone_name = await self.calendar_timezone(calendar_id)

        if calendar_id not in self._calendar_ids():
            raise IntegrationUnavailable("Calendar not configured")

        if preferred.tzinfo is None:
            raise IntegrationUnavailable("Timezone-aware time required")

        token = os.getenv("GHL_API_TOKEN", "").strip()
        if not token:
            raise IntegrationUnavailable('GHL token missing')
        start = preferred.astimezone(timezone.utc) - timedelta(hours=12)
        end = start + timedelta(days=7)
        headers = {'Authorization': f'Bearer {token}',
                   'Version': os.getenv('GHL_API_VERSION', '2021-07-28'),
                   'Accept': 'application/json'}
        params = {'startDate': int(start.timestamp()*1000),
                  'endDate': int(end.timestamp()*1000),
                  'timeZone': timezone_name, 'userId': groomer_id}
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
