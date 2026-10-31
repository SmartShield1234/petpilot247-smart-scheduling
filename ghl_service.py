
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

GHL_API_URL = "https://services.leadconnectorhq.com"


async def get_ghl_calendar(calendar_id: str):
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise ValueError("Calendar ID is required")

    token = os.getenv("GHL_API_TOKEN")

    if not token:
        raise ValueError("GHL API token is not configured")

    headers = {
        "Authorization": f"Bearer {token}",
        "Version": os.getenv(
            "GHL_API_VERSION",
            "2021-07-28"
        ),
        "Accept": "application/json"
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{GHL_API_URL}/calendars/{calendar_id}",
            headers=headers
        )
        response.raise_for_status()
        return response.json()



from datetime import datetime, timedelta, timezone


async def get_ghl_appointments(
    days_ahead: int = 7,
    requested_start: datetime | None = None,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
):
    token = os.getenv("GHL_API_TOKEN")
    location_id = os.getenv("GHL_LOCATION_ID")
    calendar_id = os.getenv("GHL_CALENDAR_ID")

    calendar_ids_raw = os.getenv(
        "GHL_SCHEDULING_CALENDAR_IDS", ""
    )

    scheduling_calendar_ids = [
        item.strip()
        for item in calendar_ids_raw.split(",")
        if item.strip()
    ]


    if not all([token, location_id, scheduling_calendar_ids]):
        raise ValueError("GHL configuration is incomplete")



    if range_start is not None or range_end is not None:
        if range_start is None or range_end is None:
            raise ValueError("Both range_start and range_end are required")

        if range_start.tzinfo is None or range_end.tzinfo is None:
            raise ValueError("Date ranges must include a timezone")

        start = range_start.astimezone(timezone.utc)
        end = range_end.astimezone(timezone.utc)

        if start >= end:
            raise ValueError("range_start must be before range_end")

    elif requested_start is not None:
        if requested_start.tzinfo is None:
            raise ValueError("Requested start must include timezone")

        start = requested_start.astimezone(timezone.utc) - timedelta(days=1)
        end = requested_start.astimezone(timezone.utc) + timedelta(days=2)

    else:
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days_ahead)



    headers = {
        "Authorization": f"Bearer {token}",
        "Version": os.getenv("GHL_API_VERSION", "2021-07-28"),
        "Accept": "application/json"
    }


    # Fetch appointments from every configured scheduling calendar.
    if not scheduling_calendar_ids:
        raise ValueError(
            "No GHL scheduling calendars configured"
        )

    if len(set(scheduling_calendar_ids)) != len(scheduling_calendar_ids):
        raise ValueError("Duplicate GHL scheduling calendar IDs")

    all_events = []
    checked_calendar_ids = []

    async with httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=10.0,
        read=45.0,
        write=10.0,
        pool=10.0,
    )
) as client:
        for current_calendar_id in scheduling_calendar_ids:
            params = {
                "locationId": location_id,
                "calendarId": current_calendar_id,
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
            }

            response = await client.get(
                f"{GHL_API_URL}/calendars/events",
                headers=headers,
                params=params,
            )

            # A failed calendar request must stop the entire operation.
            response.raise_for_status()


            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Invalid GHL calendar response")



            events = data.get("events")

            if not isinstance(events, list):
                raise ValueError(
                    "Missing or invalid GHL events list"
                )

            if (
                data.get("hasMore") is True
                or data.get("nextPage")
                or data.get("nextCursor")
            ):
                raise RuntimeError(
                    "GHL appointment response indicates additional results"
                )

            all_events.extend(events)
            checked_calendar_ids.append(current_calendar_id)



        if set(checked_calendar_ids) != set(scheduling_calendar_ids):
         raise ValueError("Incomplete GHL calendar coverage")

        return {
        "events": all_events,
        "calendars_checked": len(checked_calendar_ids),
        "checked_calendar_ids": checked_calendar_ids,
    }



async def get_ghl_contact(contact_id: str):
    """Retrieve a contact from the GHL Contacts API."""

    if not contact_id or not contact_id.strip():
        raise ValueError("Contact ID is required")

    token = os.getenv("GHL_API_TOKEN")

    if not token:
        raise ValueError("GHL API token is missing")

    headers = {
        "Authorization": f"Bearer {token}",
        "Version": os.getenv("GHL_API_VERSION", "2021-07-28"),
        "Accept": "application/json"
    }

    url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            print("GHL Contact API status:", response.status_code)

            try:
                error = response.json()
                print("GHL error message:", error.get("message", error))
            except ValueError:
                print("GHL returned a non-JSON error response")

        response.raise_for_status()
        return response.json()
