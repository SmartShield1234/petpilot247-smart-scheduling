
"""Geographic eligibility adapter for PetPilot247.

Requires a server-controlled authoritative provider.
Does not grant approvals or authorize live booking.

The authority must provide date-specific, timezone-aware working
hours. Missing, invalid, or unverified data fails closed.
"""

from datetime import date, datetime, timezone
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
        """Verify staff eligibility using a server-controlled authority."""

        # Step 1: Validate required identity and address inputs.
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

        # Step 2: Require appointment date and timezone.
        # Legacy three-argument calls fail closed.
        if (
            type(appointment_date) is not date
            or not isinstance(timezone_name, str)
            or not timezone_name.strip()
        ):
            raise IntegrationUnavailable(
                "Verified appointment date and timezone required"
            )

        # Step 3: Validate the requested timezone.
        try:
            local_timezone = ZoneInfo(timezone_name)
        except (
            ZoneInfoNotFoundError,
            ValueError,
            TypeError,
        ) as exc:
            raise IntegrationUnavailable(
                "Invalid appointment timezone"
            ) from exc

        # Step 4: Require an installed authoritative provider.
        if self.authority is None:
            raise IntegrationUnavailable(
                "Authoritative geographic eligibility service unavailable"
            )

        # Step 5: Retrieve the authoritative staff result.
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

        # Step 6: Validate the response type.
        if not isinstance(staff, Staff):
            raise IntegrationUnavailable(
                "Invalid authoritative staff response"
            )

        # Step 7: Require explicit approval.
        if staff.approved is not True:
            raise IntegrationUnavailable(
                "Groomer not approved for mobile grooming"
            )

        # Step 8: Require verified geographic eligibility.
        if staff.territory_verified is not True:
            raise IntegrationUnavailable(
                "Verified geographic eligibility unavailable"
            )

        # Step 9: Validate timezone-aware working hours.
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

        # Step 10: Require working hours on the requested local date.
        local_start = start.astimezone(local_timezone)
        local_end = end.astimezone(local_timezone)

        if (
            local_start.date() != appointment_date
            or local_end.date() != appointment_date
        ):
            raise IntegrationUnavailable(
                "Date-specific working hours unavailable"
            )

        # Step 11: Compare actual instants in UTC.
        # Local wall-clock comparisons can be wrong during DST.
        if (
            start.astimezone(timezone.utc)
            >= end.astimezone(timezone.utc)
        ):
            raise IntegrationUnavailable(
                "Invalid working time range"
            )

        # Step 12: Reject ambiguous or nonexistent local times.
        #
        # Both DST folds are examined. A boundary is accepted only
        # when it has exactly one valid UTC offset.
        #
        # This intentionally rejects ambiguous working-hour
        # boundaries until a trusted authority provides an
        # explicitly verified DST interpretation.
        for value in (start, end):
            local = value.astimezone(local_timezone)
            wall_time = local.replace(tzinfo=None)

            valid_offsets = set()

            for fold in (0, 1):
                candidate = wall_time.replace(
                    tzinfo=local_timezone,
                    fold=fold,
                )

                round_trip = (
                    candidate.astimezone(timezone.utc)
                    .astimezone(local_timezone)
                )

                if (
                    round_trip.replace(tzinfo=None)
                    == wall_time
                ):
                    valid_offsets.add(
                        candidate.utcoffset()
                    )

            if len(valid_offsets) != 1:
                raise IntegrationUnavailable(
                    "Ambiguous or invalid DST working time"
                )

        # Step 13: Require a verified depot address.
        if (
            not isinstance(staff.depot_address, str)
            or not staff.depot_address.strip()
        ):
            raise IntegrationUnavailable(
                "Verified groomer depot unavailable"
            )

        # Step 14: Validate scheduling buffers.
        for value in (
            staff.setup_minutes,
            staff.cleanup_minutes,
            staff.buffer_minutes,
        ):
            if type(value) is not int or value < 0:
                raise IntegrationUnavailable(
                    "Invalid scheduling buffer configuration"
                )

        # Step 15: Return the validated Staff object.
        #
        # This does not independently authenticate the source,
        # verify identity provenance or evidence freshness,
        # or authorize live booking.
        return staff
