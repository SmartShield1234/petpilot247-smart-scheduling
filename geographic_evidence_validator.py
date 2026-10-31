
"""Fail-closed validation of PetPilot247 geographic evidence.

This validates record structure and operational completeness.
It does not authenticate the evidence source or authorize booking.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from geographic_territory_checker import normalize_zip


def validate_geographic_evidence(
    record: dict | None,
    calendar_id: str,
    groomer_id: str,
) -> dict:
    """Check identity, verification and scheduling metadata."""

    def reject(reason: str) -> dict:
        return {
            "valid": False,
            "reason": reason,
        }

    if not isinstance(record, dict):
        return reject("Missing geographic evidence")

    if not calendar_id or not groomer_id:
        return reject("Missing requested groomer identity")

    if (
        record.get("calendar_id") != calendar_id
        or record.get("ghl_user_id") != groomer_id
    ):
        return reject("Calendar or groomer identity mismatch")

    if record.get("geographic_eligibility_verified") is not True:
        return reject("Geographic eligibility not verified")

    verification = record.get("verification")

    if not isinstance(verification, dict):
        return reject("Missing verification metadata")

    if not isinstance(verification.get("source"), str) or not verification["source"].strip():
        return reject("Missing verification source")

    if not isinstance(verification.get("reviewed_by"), str) or not verification["reviewed_by"].strip():
        return reject("Missing verification reviewer")

    verified_at = verification.get("verified_at")

    if not isinstance(verified_at, str):
        return reject("Missing verification timestamp")

    try:
        timestamp = datetime.fromisoformat(
            verified_at.replace("Z", "+00:00")
        )
    except (ValueError, OverflowError):
        return reject("Invalid verification timestamp")

    if timestamp.tzinfo is None:
        return reject("Verification timestamp lacks timezone")

    now = datetime.now(timezone.utc)

    if timestamp > now:
        return reject("Future-dated verification")

    if now - timestamp > timedelta(hours=24):
        return reject("Expired verification")

    territory = record.get("service_territory")

    if not isinstance(territory, dict):
        return reject("Missing service territory")

    if territory.get("verified") is not True:
        return reject("Service territory not verified")

    if territory.get("type") != "zip_codes":
        return reject("Unsupported service territory type")

    zip_codes = territory.get("zip_codes")

    if not isinstance(zip_codes, list) or not zip_codes:
        return reject("Missing approved ZIP codes")

    if any(normalize_zip(value) is None for value in zip_codes):
        return reject("Invalid approved ZIP codes")

    # A verified negative approval is meaningful evidence,
    # but it must never be treated as booking authorization.
    if record.get("approved_for_mobile_grooming") is not True:
        return reject("Groomer not approved for mobile grooming")

    depot = record.get("depot_address")

    if not isinstance(depot, str) or len(depot.strip()) < 5:
        return reject("Missing verified depot address")

    schedule = record.get("working_schedule")

    if not isinstance(schedule, dict):
        return reject("Missing working schedule")

    if schedule.get("verified") is not True:
        return reject("Working schedule not verified")

    timezone_name = schedule.get("timezone")

    try:
        if not isinstance(timezone_name, str):
            raise ValueError("Missing timezone")
        ZoneInfo(timezone_name)
    except (ValueError, KeyError):
        return reject("Invalid working schedule timezone")

    days = schedule.get("days")

    if not isinstance(days, list) or not days:
        return reject("Missing working days")

    if any(
        not isinstance(day, str) or not day.strip()
        for day in days
    ):
        return reject("Invalid working days")

    for field in ("start_time", "end_time"):
        value = schedule.get(field)
        if not isinstance(value, str):
            return reject(f"Missing {field}")

        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            return reject(f"Invalid {field}")

    if schedule["start_time"] >= schedule["end_time"]:
        return reject("Invalid working time range")

    buffers = record.get("scheduling_buffers")

    if not isinstance(buffers, dict):
        return reject("Missing scheduling buffers")

    if buffers.get("verified") is not True:
        return reject("Scheduling buffers not verified")

    for field in (
        "setup_minutes",
        "cleanup_minutes",
        "buffer_minutes",
    ):
        value = buffers.get(field)

        if type(value) is not int or value < 0 or value > 240:
            return reject(f"Invalid {field}")

    return {
        "valid": True,
        "reason": "Evidence structure and operational fields validated",
    }
