"""Read-only, unverified appointment-row extraction for Person 1 Step 3.

This module deliberately NEVER produces a trusted scheduling Snapshot. A separate
checkpoint-matched, eleven-calendar synchronization and address confirmation
process must attest the whole snapshot before recommendation use.
"""
from datetime import datetime

class SnapshotEvidenceError(RuntimeError):
    pass


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise SnapshotEvidenceError('Invalid appointment time') from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotEvidenceError('Timezone-aware appointment time required')
    return value


def validate_appointment_rows(rows, *, expected_calendar_ids, location_id):
    """Validate rows without inventing groomers, addresses, or sync trust."""
    ids = list(expected_calendar_ids)
    if len(ids) != 11 or len(set(ids)) != 11 or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise SnapshotEvidenceError('11 distinct configured calendar IDs required')
    if not isinstance(location_id, str) or not location_id.strip():
        raise SnapshotEvidenceError('Trusted location ID required')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 9:
            raise SnapshotEvidenceError('Unexpected PostgreSQL appointment row')
        loc, appointment_id, calendar_id, groomer_id, status, start, end, updated, deleted = row
        if loc != location_id or calendar_id not in ids:
            raise SnapshotEvidenceError('Untrusted appointment location/calendar')
        if not isinstance(appointment_id, str) or not appointment_id.strip() or appointment_id in seen:
            raise SnapshotEvidenceError('Duplicate or missing appointment ID')
        seen.add(appointment_id)
        if not isinstance(groomer_id, str) or not groomer_id.strip():
            raise SnapshotEvidenceError('Groomer identity missing')
        if not isinstance(status, str) or not status.strip():
            raise SnapshotEvidenceError('Appointment status unknown')
        start, end, updated = _aware(start), _aware(end), _aware(updated)
        if end <= start:
            raise SnapshotEvidenceError('Invalid appointment duration')
        if deleted not in (False, True, 0, 1):
            raise SnapshotEvidenceError('Invalid tombstone flag')
        result.append({'appointment_id': appointment_id, 'calendar_id': calendar_id,
                       'groomer_id': groomer_id, 'status': status,
                       'start': start, 'end': end, 'date_updated': updated,
                       'is_deleted': bool(deleted)})
    return result


def read_unverified_appointment_rows(*, connection_url, location_id,
                                    expected_calendar_ids, range_start, range_end):
    """Read rows from a transactionally consistent PostgreSQL view. No writes."""
    if not isinstance(connection_url, str) or not connection_url.strip():
        raise SnapshotEvidenceError('PostgreSQL connection required')
    start, end = _aware(range_start), _aware(range_end)
    if end <= start:
        raise SnapshotEvidenceError('Invalid snapshot range')
    ids = list(expected_calendar_ids)
    if len(ids) != 11 or len(set(ids)) != 11:
        raise SnapshotEvidenceError('Complete calendar configuration required')
    import psycopg
    with psycopg.connect(connection_url, sslmode='require', connect_timeout=15) as conn:
        with conn.cursor() as cursor:
            cursor.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cursor.execute('''SELECT location_id, appointment_id, calendar_id,
                assigned_user_id, appointment_status, start_time, end_time,
                date_updated, is_deleted FROM appointments
                WHERE location_id = %s AND start_time < %s AND end_time > %s''',
                (location_id, end.isoformat(), start.isoformat()))
            rows = cursor.fetchall()
            cursor.execute('ROLLBACK')
    return {'appointments': validate_appointment_rows(rows, expected_calendar_ids=ids,
                                                      location_id=location_id),
            'sync_verified': False, 'complete_all_calendars': False,
            'booking_authorized': False,
            'reason': 'Rows alone do not establish GHL coverage, checkpoint, confirmed service addresses, or authorization'}
