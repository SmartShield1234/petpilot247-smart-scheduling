
from datetime import date, datetime


def parse_ghl_free_slots(response):
    """
    Parse GHL free-slot response structure.

    Read-only transformation.
    Does not authorize bookings.
    """

    if not isinstance(response, dict):
        raise ValueError("Invalid GHL free-slot response")

    allowed_metadata = {"traceId"}

    slots_by_date = {}

    for key, value in response.items():
        if key in allowed_metadata:
            continue

        # GHL date entries must be valid ISO calendar dates.
        try:
            parsed_date = date.fromisoformat(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Unexpected GHL free-slot response field"
            ) from exc

        if parsed_date.isoformat() != key:
            raise ValueError("Invalid free-slot date key")

        if not isinstance(value, dict):
            raise ValueError("Invalid free-slot day entry")

        slots = value.get("slots")

        if not isinstance(slots, list):
            raise ValueError("Missing or invalid slots list")

        parsed_slots = []

        for slot in slots:
            if not isinstance(slot, str):
                raise ValueError("Invalid free-slot timestamp")

            try:
                timestamp = datetime.fromisoformat(
                    slot.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError(
                    "Invalid free-slot timestamp"
                ) from exc

            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(
                    "Timezone-aware free-slot timestamp required"
                )

            if timestamp.date() != parsed_date:
                # Timezone conversion may move the calendar date.
                # Do not make assumptions about GHL's date grouping.
                pass

            parsed_slots.append(timestamp)

        slots_by_date[key] = parsed_slots

    return {
        "slots_by_date": slots_by_date,
        "total_slots": sum(
            len(items) for items in slots_by_date.values()
        ),
        "booking_authorized": False,
        "verification_status": "free_slots_only",
    }
