
"""Fail-closed ZIP-code territory matching for PetPilot247.

This checker does not authenticate business approvals or authorize bookings.
Only use its result as one input to a separately verified authority.
"""

import re


def normalize_zip(value):
    """Accept only a five-digit US ZIP code."""
    if not isinstance(value, str):
        return None

    value = value.strip()

    if not re.fullmatch(r"[0-9]{5}", value):
        return None

    return value


def check_territory(customer_zip, territory):
    """Return True only for a verified, matching ZIP-code territory."""
    zip_code = normalize_zip(customer_zip)

    if zip_code is None or not isinstance(territory, dict):
        return False

    if territory.get("verified") is not True:
        return False

    if territory.get("type") != "zip_codes":
        return False

    allowed = territory.get("zip_codes")

    if not isinstance(allowed, list) or not allowed:
        return False

    if any(normalize_zip(item) is None for item in allowed):
        return False

    return zip_code in allowed
