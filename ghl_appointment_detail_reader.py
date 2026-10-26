"""Read a GHL appointment by ID.

Read-only integration. Does not authorize bookings.
"""

import os
import re
import httpx


async def get_ghl_appointment_detail(event_id, *, client=None):
    if not isinstance(event_id, str):
        raise ValueError("Appointment ID required")

    event_id = event_id.strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
        raise ValueError("Invalid appointment ID")

    token = os.getenv("GHL_API_TOKEN", "").strip()
    version = os.getenv("GHL_APPOINTMENT_API_VERSION", "2023-02-21")

    if not token:
        raise RuntimeError("GHL API token not configured")

    if version not in {"2023-02-21", "v3"}:
        raise ValueError("Unsupported appointment API version")

    url = (
        "https://services.leadconnectorhq.com"
        "/calendars/events/appointments/"
        + event_id
    )

    headers = {
        "Authorization": "Bearer " + token,
        "Version": version,
        "Accept": "application/json",
    }

    owns_client = client is None

    if owns_client:
        client = httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
        )

    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Invalid GHL response")

        # HighLevel API versions may wrap appointment details
        # under "event" or "appointment".
        event = data.get("event")

        if event is None:
            event = data.get("appointment")

        if not isinstance(event, dict):
            raise ValueError("Missing GHL appointment event")

        if event.get("id") != event_id:
            raise ValueError("GHL appointment ID mismatch")

        return event

    finally:
        if owns_client:
            await client.aclose()
