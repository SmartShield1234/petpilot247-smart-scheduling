"""Fail-closed factory for the Person 1 read-only scheduling provider.

Authority implementations must be supplied by independently authenticated services.
No default callback can invent synchronization, calendar, staff, or route evidence.
"""
from pavi_live_ghl_provider import LiveGHLProviders, IntegrationUnavailable


def build_live_providers(*, snapshot_authority=None,
                         appointment_snapshot_authority=None,
                         staff_authority=None,
                         calendar_timezone_authority=None,
                         routes=None, http_client=None):
    required = {
        'snapshot_authority': snapshot_authority,
        'appointment_snapshot_authority': appointment_snapshot_authority,
        'staff_authority': staff_authority,
        'calendar_timezone_authority': calendar_timezone_authority,
    }
    missing = [name for name, fn in required.items() if not callable(fn)]
    if missing:
        raise IntegrationUnavailable('Trusted provider authorities unavailable: ' + ', '.join(missing))
    return LiveGHLProviders(**required, routes=routes, http_client=http_client)
