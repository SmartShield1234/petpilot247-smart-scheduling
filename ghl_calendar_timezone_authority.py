"""Read-only, authenticated GHL calendar timezone authority for Person 1 Step 3.

Only calendar API evidence with a matching calendar ID is accepted. No hardcoded
fallback timezone is permitted, even when the business operates in one zone.
"""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ghl_service import get_ghl_calendar


class CalendarTimezoneUnavailable(RuntimeError):
    pass


async def authenticated_calendar_timezone(calendar_id: str) -> str:
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise CalendarTimezoneUnavailable("Valid calendar ID required")
    try:
        payload = await get_ghl_calendar(calendar_id)
    except Exception as exc:
        raise CalendarTimezoneUnavailable("Authenticated calendar lookup unavailable") from exc
    if not isinstance(payload, dict):
        raise CalendarTimezoneUnavailable("Invalid calendar response")
    calendar = payload.get("calendar")
    if not isinstance(calendar, dict):
        # Some API clients return the calendar directly rather than wrapped.
        calendar = payload
    if calendar.get("id") != calendar_id:
        raise CalendarTimezoneUnavailable("Calendar identity mismatch")
    value = calendar.get("timezone")
    if value is None:
        value = calendar.get("timeZone")
    if not isinstance(value, str) or not value.strip():
        raise CalendarTimezoneUnavailable("Calendar timezone not present in authenticated record")
    value = value.strip()
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarTimezoneUnavailable("Calendar timezone not recognized") from exc
    return value
