
"""Fail-closed assembly of PetPilot247 scheduling authorities.

Authority callbacks must obtain genuine, authenticated evidence.
This module does not verify sync, approve groomers, or authorize booking.
"""

from collections.abc import Callable

from geographic_staff_bridge import create_geographic_staff_authority
from pavi_provider_factory import build_live_providers
from pavi_live_ghl_provider import IntegrationUnavailable


def create_step3_provider(
    *,
    sync_authority=None,
    appointment_authority=None,
    authenticated_staff_authority=None,
    calendar_timezone_authority=None,
    routes=None,
    http_client=None,
):
    """Assemble existing trusted scheduling providers."""

    required = {
        "sync_authority": sync_authority,
        "appointment_authority": appointment_authority,
        "authenticated_staff_authority": authenticated_staff_authority,
        "calendar_timezone_authority": calendar_timezone_authority,
    }

    missing = [
        name
        for name, authority in required.items()
        if not callable(authority)
    ]

    if missing:
        raise IntegrationUnavailable(
            "Missing trusted Step 3 authorities: "
            + ", ".join(missing)
        )

    staff_authority = create_geographic_staff_authority(
        authenticated_authority=authenticated_staff_authority
    )

    return build_live_providers(
        snapshot_authority=sync_authority,
        appointment_snapshot_authority=appointment_authority,
        staff_authority=staff_authority,
        calendar_timezone_authority=calendar_timezone_authority,
        routes=routes,
        http_client=http_client,
    )
