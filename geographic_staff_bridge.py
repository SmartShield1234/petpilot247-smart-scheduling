
"""PetPilot247 geographic staff integration bridge.

Connects the existing geographic adapter to Pavi's provider.

No live authority is installed by default.
No local JSON approvals are accepted.
"""

from geographic_eligibility_adapter import GeographicEligibilityAdapter
from pavi_live_ghl_provider import LiveGHLProviders


def create_geographic_staff_authority(
    authenticated_authority=None,
):
    """Create the staff authority callable for Pavi's provider.

    authenticated_authority must be a trusted server-side
    async function returning verified Staff data.

    Never supply a client-controlled function or unverified
    local JSON record.
    """

    adapter = GeographicEligibilityAdapter(
        authority=authenticated_authority,
    )

    async def staff_authority(
        calendar_id: str,
        groomer_id: str,
        customer_address: str,
    ):
        return await adapter.verify(
            calendar_id,
            groomer_id,
            customer_address,
        )

    return staff_authority


def create_geographic_enabled_provider(
    authenticated_authority=None,
    **provider_options,
):
    """Construct Pavi's provider with geographic validation."""

    staff_authority = create_geographic_staff_authority(
        authenticated_authority=authenticated_authority,
    )

    return LiveGHLProviders(
        staff_authority=staff_authority,
        **provider_options,
    )
