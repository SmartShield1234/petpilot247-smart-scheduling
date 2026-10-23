"""Deterministic appointment feasibility and ranking core.

All inputs must come from independently trusted providers. This module does not
fetch GHL or Maps data and never authorizes bookings.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence


def aware(t: datetime) -> datetime:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError('Timezone-aware datetime required')
    return t.astimezone(timezone.utc)


@dataclass(frozen=True)
class Appointment:
    start: datetime
    end: datetime
    address: str
    appointment_id: str

    def __post_init__(self):
        if aware(self.end) <= aware(self.start):
            raise ValueError('Appointment end must follow start')
        if not self.address or not self.appointment_id:
            raise ValueError('Confirmed address and appointment ID required')


@dataclass(frozen=True)
class Candidate:
    groomer_id: str
    start: datetime
    work_start: datetime
    work_end: datetime
    free_starts: frozenset[datetime]
    appointments: tuple[Appointment, ...]
    service_minutes: int
    setup_minutes: int
    cleanup_minutes: int
    buffer_minutes: int
    previous_drive_minutes: float
    next_drive_minutes: float
    direct_drive_minutes: float
    preferred_start: datetime
    evidence_verified: bool = False


def evaluate(candidate: Candidate) -> dict | None:
    """Fail closed unless all eligibility and upstream evidence are confirmed.

    The caller must prove evidence_verified using server-side authenticated
    providers; a customer request must never set this field.
    """
    if candidate.evidence_verified is not True or not candidate.groomer_id:
        return None
    numeric = (candidate.service_minutes, candidate.setup_minutes,
               candidate.cleanup_minutes, candidate.buffer_minutes,
               candidate.previous_drive_minutes, candidate.next_drive_minutes,
               candidate.direct_drive_minutes)
    import math
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or v < 0 for v in numeric):
        return None
    if candidate.service_minutes <= 0:
        return None
    start = aware(candidate.start)
    work_start = aware(candidate.work_start)
    work_end = aware(candidate.work_end)
    end = start + timedelta(minutes=candidate.service_minutes)
    if start not in {aware(t) for t in candidate.free_starts}:
        return None
    if not (work_start <= start and end <= work_end):
        return None
    appointments = sorted(candidate.appointments, key=lambda a: aware(a.start))
    # Reject every overlap, including appointments on other calendars for this groomer.
    if any(start < aware(a.end) and end > aware(a.start) for a in appointments):
        return None
    previous = [a for a in appointments if aware(a.end) <= start]
    following = [a for a in appointments if aware(a.start) >= end]
    prev_end = aware(previous[-1].end) if previous else work_start
    next_start = aware(following[0].start) if following else work_end
    earliest = prev_end + timedelta(minutes=candidate.previous_drive_minutes + candidate.setup_minutes)
    latest_leave = end + timedelta(minutes=candidate.cleanup_minutes + candidate.buffer_minutes + candidate.next_drive_minutes)
    if start < earliest or latest_leave > next_start:
        return None
    added_drive = max(0.0, candidate.previous_drive_minutes + candidate.next_drive_minutes - candidate.direct_drive_minutes)
    preference = abs((start - aware(candidate.preferred_start)).total_seconds()) / 60
    return {'groomer_id': candidate.groomer_id, 'start_time': start.isoformat(),
            'end_time': end.isoformat(), 'added_drive_minutes': round(added_drive, 2),
            'preference_deviation_minutes': round(preference, 2),
            'booking_authorized': False}


def best_slots(candidates: Sequence[Candidate], limit: int = 5) -> list[dict]:
    if not 1 <= limit <= 5:
        raise ValueError('Result limit must be 1 to 5')
    rows = [row for c in candidates if (row := evaluate(c)) is not None]
    rows.sort(key=lambda row: (row['added_drive_minutes'], row['preference_deviation_minutes'], row['start_time']))
    return rows[:limit]
