"""Strict server-side orchestration of independently sourced scheduling evidence.

Adapters MUST authenticate and retrieve data themselves. Never pass client-provided
availability, appointment records, eligibility, driving minutes, or verification flags.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from pavi_slot_validator import Candidate, Appointment, best_slots


@dataclass(frozen=True)
class Request:
    calendar_id: str
    customer_address: str
    preferred_start: datetime
    service_minutes: int
    max_results: int = 5


@dataclass(frozen=True)
class Snapshot:
    sync_verified: bool
    complete_all_calendars: bool
    groomer_ids: tuple[str, ...]
    appointments_by_groomer: dict[str, tuple[Appointment, ...]]


@dataclass(frozen=True)
class Staff:
    approved: bool
    territory_verified: bool
    work_start: datetime
    work_end: datetime
    depot_address: str
    setup_minutes: int
    cleanup_minutes: int
    buffer_minutes: int


class Providers(Protocol):
    async def appointments(self, calendar_id: str) -> Snapshot: ...
    async def staff(self, calendar_id: str, groomer_id: str, address: str) -> Staff: ...
    async def free_starts(self, calendar_id: str, groomer_id: str,
                          preferred: datetime) -> frozenset[datetime]: ...
    async def travel(self, origin: str, destination: str) -> float: ...


async def recommend(request: Request, providers: Providers) -> dict:
    """Fail closed: no verified evidence, no customer recommendations."""
    if not request.calendar_id.strip() or not request.customer_address.strip():
        raise ValueError('Calendar and customer address required')
    if request.service_minutes <= 0 or not 1 <= request.max_results <= 5:
        raise ValueError('Invalid service duration or result count')
    if request.preferred_start.tzinfo is None:
        raise ValueError('Timezone-aware preferred time required')
    try:
        snapshot = await providers.appointments(request.calendar_id)
        if snapshot.sync_verified is not True or snapshot.complete_all_calendars is not True:
            return _blocked('Appointment synchronization not verified')
        candidates = []
        for groomer_id in snapshot.groomer_ids:
            staff = await providers.staff(request.calendar_id, groomer_id,
                                          request.customer_address)
            if staff.approved is not True or staff.territory_verified is not True:
                continue
            appointments = snapshot.appointments_by_groomer.get(groomer_id)
            if appointments is None:
                continue
            starts = await providers.free_starts(request.calendar_id, groomer_id,
                                                 request.preferred_start)
            if not starts:
                continue
            ordered = sorted(appointments, key=lambda appt: appt.start)
            for start in sorted(starts):
                end = start + __import__('datetime').timedelta(minutes=request.service_minutes)
                if any(start < a.end and end > a.start for a in ordered):
                    continue
                prior = [a for a in ordered if a.end <= start]
                later = [a for a in ordered if a.start >= end]
                prior_addr = prior[-1].address if prior else staff.depot_address
                next_addr = later[0].address if later else staff.depot_address
                # All route durations must originate from the provider, never the caller.
                incoming = await providers.travel(prior_addr, request.customer_address)
                outgoing = await providers.travel(request.customer_address, next_addr)
                direct = await providers.travel(prior_addr, next_addr)
                candidates.append(Candidate(
                    groomer_id=groomer_id, start=start,
                    work_start=staff.work_start, work_end=staff.work_end,
                    free_starts=starts, appointments=appointments,
                    service_minutes=request.service_minutes,
                    setup_minutes=staff.setup_minutes,
                    cleanup_minutes=staff.cleanup_minutes,
                    buffer_minutes=staff.buffer_minutes,
                    previous_drive_minutes=incoming, next_drive_minutes=outgoing,
                    direct_drive_minutes=direct, preferred_start=request.preferred_start,
                    evidence_verified=True,
                ))
        return {'recommendations': best_slots(candidates, request.max_results),
                'booking_authorized': False, 'source': 'verified_server_side_providers'}
    except Exception:
        # Provider failures must never turn into apparently valid recommendations.
        return _blocked('Verified upstream evidence unavailable')


def _blocked(reason: str) -> dict:
    return {'recommendations': [], 'booking_authorized': False,
            'reason': reason}
