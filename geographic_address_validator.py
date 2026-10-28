
"""Validate trusted address-verification results for PetPilot247.

This module validates the structure and identity of an address result.
It does not call Google Maps or authenticate the source itself.
"""

from geographic_territory_checker import normalize_zip


def validate_confirmed_address(
    requested_address: str,
    address_evidence: dict | None,
) -> dict:
    """Return a ZIP only when the supplied evidence is consistent."""

    unavailable = {
        "valid": False,
        "customer_zip": None,
        "reason": "Confirmed customer address unavailable",
    }

    if not isinstance(requested_address, str):
        return unavailable

    if len(requested_address.strip()) < 5:
        return unavailable

    if not isinstance(address_evidence, dict):
        return unavailable

    # Evidence must identify the exact address request.
    if address_evidence.get("requested_address") != requested_address:
        return unavailable

    if address_evidence.get("verified") is not True:
        return unavailable

    if address_evidence.get("country_code") != "US":
        return unavailable

    if address_evidence.get("address_complete") is not True:
        return unavailable

    if address_evidence.get("location_type") != "ROOFTOP":
        return unavailable

    customer_zip = normalize_zip(
        address_evidence.get("postal_code")
    )

    if customer_zip is None:
        return unavailable

    formatted_address = address_evidence.get("formatted_address")

    if (
        not isinstance(formatted_address, str)
        or len(formatted_address.strip()) < 10
    ):
        return unavailable

    return {
        "valid": True,
        "customer_zip": customer_zip,
        "reason": "Confirmed address evidence structurally validated",
    }
