
"""Geographic eligibility adapter for PetPilot247.

Requires a server-controlled authoritative provider.
Does not grant approvals or authorize live booking.
"""

from datetime import date, datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
        appointment_date: date | None = None,
        timezone_name: str | None = None,
    ) -> Staff:

        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                calendar_id,
                groomer_id,
                customer_address,
            )
        ):
            raise IntegrationUnavailable(
                "Missing geographic eligibility inputs"
            )

        # The new date-specific contract requires both values.
        # Legacy three-argument calls fail closed.
        if (
            type(appointment_date) is not date
            or not isinstance(timezone_name, str)
            or not timezone_name.strip()
        ):
            raise IntegrationUnavailable(
                "Verified appointment date and timezone required"
            )

        try:
            timezone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise IntegrationUnavailable(
                "Invalid appointment timezone"
            )

        if self.authority is None:
            raise IntegrationUnavailable(
                "Authoritative geographic eligibility service unavailable"
            )

        try:
            staff = await self.authority(
                calendar_id,
                groomer_id,
                customer_address,
                appointment_date,
                timezone_name,
            )
        except Exception as exc:
            raise IntegrationUnavailable(
                "Authoritative staff verification unavailable"
            ) from exc

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
                "Verified geographic eligibility unavailable"
            )

        start = staff.work_start
        end = staff.work_end

        if (
            not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is None
            or end.tzinfo is None
            or start.utcoffset() is None
            or end.utcoffset() is None
        ):
            raise IntegrationUnavailable(
                "Timezone-aware working hours required"
            )

        # Require the requested local date and timezone.
        local_start = start.astimezone(timezone)
        local_end = end.astimezone(timezone)

        if (
            local_start.date() != appointment_date
            or local_end.date() != appointment_date
            or local_start >= local_end
        ):
            raise IntegrationUnavailable(
                "Date-specific working hours unavailable"
            )

        # Reject datetimes that do not represent valid local times
        # in the requested timezone, including DST gaps.
        for value in (start, end):
            local = value.astimezone(timezone)
            if local.astimezone(ZoneInfo("UTC")).astimezone(
                timezone
            ) != local:
                raise IntegrationUnavailable(
                    "Invalid daylight-saving-time schedule"
                )

        if (
            not isinstance(staff.depot_address, str)
            or not staff.depot_address.strip()
        ):
            raise IntegrationUnavailable(
                "Verified groomer depot unavailable"
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
