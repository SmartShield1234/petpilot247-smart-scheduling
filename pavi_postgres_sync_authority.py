"""Read-only PostgreSQL scheduling synchronization gate.

A 'verified' health row by itself is NOT evidence of complete 11-calendar
coverage. An independently authenticated coverage authority must attest
that the current snapshot/checkpoint includes exactly the configured set.
No database writes and no booking authorization occur here.
"""
import os
from datetime import datetime, timezone, timedelta
from collections.abc import Awaitable, Callable

import psycopg


class SyncEvidenceUnavailable(RuntimeError):
    pass


def _parse_utc(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise SyncEvidenceUnavailable('Reconciliation timestamp missing')
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SyncEvidenceUnavailable('Reconciliation timestamp must be timezone-aware')
    return dt.astimezone(timezone.utc)


async def verified_postgres_sync(*, coverage_authority: Callable[[], Awaitable[object]],
                                 connection_url=None, max_age_minutes=60,
                                 now=None):
    """Return True only if PostgreSQL health AND independently verified coverage pass.

    coverage_authority must return the authenticated, checkpoint-matched set of
    calendar IDs. Caller must ensure this attestation is bound to the same
    persisted snapshot; do not provide configured IDs as a substitute.
    """
    if not callable(coverage_authority):
        raise SyncEvidenceUnavailable('Authenticated calendar coverage authority required')
    config = [c.strip() for c in os.getenv('GHL_SCHEDULING_CALENDAR_IDS', '').split(',') if c.strip()]
    if len(config) != 11 or len(set(config)) != 11:
        raise SyncEvidenceUnavailable('Exactly 11 distinct configured calendars required')
    if not isinstance(max_age_minutes, (int, float)) or not 0 < max_age_minutes <= 1440:
        raise SyncEvidenceUnavailable('Invalid freshness limit')
    connection_url = connection_url or os.getenv('PETPILOT_POSTGRES_URL', '').strip()
    if not connection_url:
        raise SyncEvidenceUnavailable('PostgreSQL connection missing')
    if os.getenv('PETPILOT_LIVE_BOOKING_ENABLED', '').lower().strip() != 'false':
        raise SyncEvidenceUnavailable('Live booking must remain disabled')
    with psycopg.connect(connection_url, sslmode='require', connect_timeout=15) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT status, last_reconciled_at FROM appointment_sync_health WHERE id = 1')
            row = cursor.fetchone()
    if not row or row[0] != 'verified':
        raise SyncEvidenceUnavailable('PostgreSQL synchronization not verified')
    reconciled = _parse_utc(row[1])
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise SyncEvidenceUnavailable('Invalid reference time')
    age = now.astimezone(timezone.utc) - reconciled
    if age < timedelta(0) or age > timedelta(minutes=max_age_minutes):
        raise SyncEvidenceUnavailable('Synchronization checkpoint is stale or future-dated')
    covered = await coverage_authority()
    if not isinstance(covered, (set, frozenset, list, tuple)):
        raise SyncEvidenceUnavailable('Trusted calendar coverage evidence missing')
    if len(covered) != 11 or len(set(covered)) != 11 or set(covered) != set(config):
        raise SyncEvidenceUnavailable('Incomplete or untrusted calendar coverage')
    return True
