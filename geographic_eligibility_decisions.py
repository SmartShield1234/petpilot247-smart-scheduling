
"""Geographic eligibility decisions for PetPilot247.

Never treat an unverified JSON record as authoritative evidence.

The trusted_source parameter is for controlled integration and
testing only. It is not an authentication mechanism and must
never be exposed as a client-controlled input.

Production eligibility requires independently authenticated,
business-approved, current geographic evidence.
"""

from datetime import datetime, timedelta, timezone

from geographic_territory_checker import (
    check_territory,
    normalize_zip,
)


def decide_eligibility(
    customer_zip: str,
    record: dict | None,
    *,
    trusted_source: bool = False,
) -> dict:
    """Evaluate geographic eligibility using trusted evidence."""

    unavailable = {
        "decision": "unavailable",
        "eligible": False,
        "evidence_verified": False,
        "reason": "Authoritative geographic evidence unavailable",
    }

    # Reject records without an authenticated authority.
    if trusted_source is not True:
        return unavailable

    if not isinstance(record, dict):
        return unavailable

    # Reject invalid customer ZIP codes.
    if normalize_zip(customer_zip) is None:
        return unavailable

    verification = record.get("verification")
    territory = record.get("service_territory")

    if not isinstance(verification, dict):
        return unavailable

    if not isinstance(territory, dict):
        return unavailable

    # Geographic approval must be explicitly verified.
    if record.get("geographic_eligibility_verified") is not True:
        return unavailable

    if territory.get("verified") is not True:
        return unavailable

    if territory.get("type") != "zip_codes":
        return unavailable

    allowed_zips = territory.get("zip_codes")

    if not isinstance(allowed_zips, list) or not allowed_zips:
        return unavailable

    if any(normalize_zip(item) is None for item in allowed_zips):
        return unavailable

    # Require verification provenance.
    if not verification.get("source"):
        return unavailable

    if not verification.get("reviewed_by"):
        return unavailable

    verified_at = verification.get("verified_at")

    if not isinstance(verified_at, str):
        return unavailable

    try:
        timestamp = datetime.fromisoformat(
            verified_at.replace("Z", "+00:00")
        )
    except (ValueError, OverflowError):
        return unavailable

    if timestamp.tzinfo is None:
        return unavailable

    # Reject future-dated or expired verification evidence.
    now = datetime.now(timezone.utc)

    if timestamp > now:
        return unavailable

    if now - timestamp > timedelta(hours=24):
        return unavailable

    # A verified negative approval means ineligible.
    if record.get("approved_for_mobile_grooming") is not True:
        return {
            "decision": "ineligible",
            "eligible": False,
            "evidence_verified": True,
            "reason": "Groomer not approved for mobile grooming",
        }

    # Check the customer's ZIP against the verified territory.
    if not check_territory(customer_zip, territory):
        return {
            "decision": "ineligible",
            "eligible": False,
            "evidence_verified": True,
            "reason": "Customer outside approved service territory",
        }

    # This result is only valid within a trusted server-side
    # authority integration. It does not authorize booking.
    return {
        "decision": "eligible",
        "eligible": True,
        "evidence_verified": True,
        "reason": "Verified territory match",
    }
