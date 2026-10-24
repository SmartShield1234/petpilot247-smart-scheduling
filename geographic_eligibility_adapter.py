
"""Trusted geographic eligibility adapter for PetPilot247.

This module does not grant geographic approval itself.
It requires independently authenticated evidence from an
authoritative staff and territory service.
"""

from datetime import datetime
from typing import Callable, Awaitable

from pavi_recommendation_pipeline import Staff
from pavi_live_ghl_provider import IntegrationUnavailable


class GeographicEligibilityAdapter:
    def __init__(
        self,
        authority: Callable[..., Awaitable[Staff]] | None = None,
    ):
        self.authority = authority

    async def verify(
        self,
        calendar_id: str,
        groomer_id: str,
        customer_address: str,
    ) -> Staff:

        if not calendar_id or not groomer_id or not customer_address:
            raise IntegrationUnavailable(
                "Missing geographic eligibility inputs"
            )

        if self.authority is None:
            raise IntegrationUnavailable(
                "Authoritative geographic eligibility service unavailable"
            )

        staff = await self.authority(
            calendar_id,
            groomer_id,
            customer_address,
        )

        if not isinstance(staff, Staff):
            raise IntegrationUnavailable(
                "Invalid authoritative staff response"
            )

        if staff.approved is not True:
            raise IntegrationUnavailable(
                "Groomer not approved for mobile grooming"
            )

        if staff.territory_verified is not True:
            raise IntegrationUnavailable(
                "Customer outside verified service territory"
            )

        if (
            not isinstance(staff.work_start, datetime)
            or not isinstance(staff.work_end, datetime)
            or staff.work_start.tzinfo is None
            or staff.work_end.tzinfo is None
            or staff.work_start.utcoffset() is None
            or staff.work_end.utcoffset() is None
            or staff.work_start >= staff.work_end
            ):
            raise IntegrationUnavailable(
                "Invalid verified working hours"
            )

        if not isinstance(staff.depot_address, str) or not staff.depot_address.strip():
            raise IntegrationUnavailable(
                "Verified groomer depot address unavailable"
            )

        for value in (
            staff.setup_minutes,
            staff.cleanup_minutes,
            staff.buffer_minutes,
        ):
            if type(value) is not int or value < 0:
                raise IntegrationUnavailable(
                    "Invalid scheduling buffer configuration"
                )

        return staff
