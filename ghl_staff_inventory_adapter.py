"""Read-only GHL grooming staff inventory adapter.

Calendar membership is not production eligibility.
"""

import json
from pathlib import Path


def get_calendar_staff(
    *,
    calendar_id,
    inventory_path="ghl_grooming_staff_inventory.json",
):
    path = Path(inventory_path)

    if not path.is_file():
        raise ValueError("GHL staff inventory missing")

    records = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(records, list):
        raise ValueError("Invalid staff inventory")

    matches = [
        item for item in records
        if isinstance(item, dict)
        and item.get("calendar_id") == calendar_id
    ]

    if len(matches) != 1:
        raise ValueError("Calendar missing or duplicated")

    record = matches[0]

    user_ids = record.get("ghl_user_ids")

    if (
        not isinstance(user_ids, list)
        or not user_ids
        or not all(
            isinstance(value, str) and value.strip()
            for value in user_ids
        )
        or len(user_ids) != len(set(user_ids))
    ):
        raise ValueError("Invalid staff assignments")

    return {
        "calendar_id": calendar_id,
        "assigned_ghl_user_ids": list(user_ids),
        "staff_count": len(user_ids),
        "production_approved": (
            record.get("approved_for_mobile_grooming") is True
        ),
        "geographic_verified": (
            record.get("geographic_eligibility_verified") is True
        ),
        "booking_authorized": False,
    }
