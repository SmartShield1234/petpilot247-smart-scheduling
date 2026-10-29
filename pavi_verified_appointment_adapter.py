"""Build scheduling appointments from corroborated PostgreSQL and GHL evidence.

Caller supplies PostgreSQL rows from a trusted reader and an independently verified
service-address resolver. This module performs no writes and never authorizes booking.
The service-address resolver MUST prove the location is the service address and was
confirmed for the current appointment revision, not merely a contact profile address.
"""
from datetime import datetime, timezone
from typing import Awaitable, Callable

from ghl_appointment_detail_reader import get_ghl_appointment_detail
from pavi_slot_validator import Appointment


class AppointmentEvidenceUnavailable(RuntimeError):
    pass


def _instant(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise AppointmentEvidenceUnavailable('Invalid appointment timestamp') from exc
    else:
        raise AppointmentEvidenceUnavailable('Missing appointment timestamp')
    if result.tzinfo is None or result.utcoffset() is None:
        raise AppointmentEvidenceUnavailable('Timezone-aware appointment timestamp required')
    return result.astimezone(timezone.utc)


async def verified_appointment_from_row(
    row: dict,
    *,
    address_authority: Callable[..., Awaitable[dict]],
    detail_reader=get_ghl_appointment_detail,
) -> Appointment:
    """Require GHL identity/revision match and independently confirmed service address.

    The resolver receives only trusted identifiers and must return a dict with:
      appointment_id, location_id, revision, service_address,
      confirmed=True, source_authenticated=True.
    All values are checked here, but actual authentication/provenance is the caller's
    responsibility. The resolver must never accept user-supplied confirmation flags.
    """
    if not isinstance(row, dict) or not callable(address_authority):
        raise AppointmentEvidenceUnavailable('Trusted appointment row and address resolver required')
    needed = ('appointment_id', 'location_id', 'calendar_id', 'assigned_user_id',
              'start_time', 'end_time', 'date_updated')
    if any(not row.get(key) for key in needed):
        raise AppointmentEvidenceUnavailable('Incomplete appointment identity')
    if row.get('is_deleted') not in (False, 0, None):
        raise AppointmentEvidenceUnavailable('Deleted appointment')
    try:
        event = await detail_reader(row['appointment_id'])
        if not isinstance(event, dict):
            raise AppointmentEvidenceUnavailable('Invalid GHL response')
        pairs = (
            ('id', 'appointment_id'), ('locationId', 'location_id'),
            ('calendarId', 'calendar_id'), ('assignedUserId', 'assigned_user_id'),
        )
        if any(event.get(ghl) != row.get(db) for ghl, db in pairs):
            raise AppointmentEvidenceUnavailable('GHL appointment identity mismatch')
        if event.get('deleted') is True:
            raise AppointmentEvidenceUnavailable('Deleted GHL appointment')
        for ghl, db in (('startTime', 'start_time'), ('endTime', 'end_time'),
                        ('dateUpdated', 'date_updated')):
            if _instant(event.get(ghl)) != _instant(row.get(db)):
                raise AppointmentEvidenceUnavailable('GHL appointment revision or time mismatch')
        start = _instant(row['start_time'])
        end = _instant(row['end_time'])
        if end <= start:
            raise AppointmentEvidenceUnavailable('Invalid appointment duration')
        address = await address_authority(
            location_id=row['location_id'], appointment_id=row['appointment_id'],
            revision=row['date_updated'],
        )
        if not isinstance(address, dict) or address.get('confirmed') is not True or address.get('source_authenticated') is not True:
            raise AppointmentEvidenceUnavailable('Authenticated service address confirmation missing')
        if (address.get('appointment_id') != row['appointment_id'] or
            address.get('location_id') != row['location_id'] or
            _instant(address.get('revision')) != _instant(row['date_updated'])):
            raise AppointmentEvidenceUnavailable('Service address confirmation is stale or mismatched')
        location = address.get('service_address')
        if not isinstance(location, str) or not location.strip():
            raise AppointmentEvidenceUnavailable('Service address missing')
        return Appointment(start=start, end=end, address=location.strip(),
                           appointment_id=row['appointment_id'])
    except AppointmentEvidenceUnavailable:
        raise
    except Exception as exc:
        raise AppointmentEvidenceUnavailable('Appointment evidence unavailable') from exc
