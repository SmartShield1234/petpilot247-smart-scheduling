
"""Staff authority bridge for PetPilot247.

Supports the agreed five-argument, date-specific contract.
Legacy three-argument calls fail closed.
"""

from datetime import date

from geographic_eligibility_adapter import GeographicEligibilityAdapter
from pavi_live_ghl_provider import LiveGHLProviders


def create_geographic_staff_authority(
    authenticated_authority=None,
):
    adapter = GeographicEligibilityAdapter(
        authority=authenticated_authority
    )

    async def staff_authority(
        calendar_id: str,
        groomer_id: str,
        customer_address: str,
        appointment_date: date | None = None,
        timezone_name: str | None = None,
    ):
        return await adapter.verify(
            calendar_id,
            groomer_id,
            customer_address,
            appointment_date,
            timezone_name,
        )

    return staff_authority


def create_geographic_enabled_provider(
    authenticated_authority=None,
    **provider_options,
):
    staff_authority = create_geographic_staff_authority(
        authenticated_authority=authenticated_authority
    )

    return LiveGHLProviders(
        staff_authority=staff_authority,
        **provider_options,
    )
