
from datetime import datetime

from groomers import TIMEZONE
from scheduling import evaluate_safe_groomer_booking

requested_start = datetime(
    2026, 10, 15, 9, 15, tzinfo=TIMEZONE
)

cases = [
    ("Missing depot travel", None, None, False),
    ("Insufficient depot travel", 30, 30, False),
    ("Enough depot travel", 10, 10, True),
]

for name, depot_minutes, return_minutes, expected in cases:
    result = evaluate_safe_groomer_booking(
        groomer_id="silpa",
        requested_start=requested_start,
        service_minutes=90,
        appointments=[],
        depot_required=True,
        depot_drive_minutes=depot_minutes,
        depot_return_minutes=return_minutes
    )

    actual = result["available"]

    assert actual == expected, (
        f"{name}: expected {expected}, got {actual}"
    )

    print(name, "| Available:", actual, "| PASS")

print("PASS: Depot travel validation completed.")
