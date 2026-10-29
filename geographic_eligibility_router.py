"""Authenticated geographic eligibility API for PetPilot247.

The geographic authority must be installed by trusted server code.
Never accept eligibility approvals or trusted-source flags from clients.

The API requires appointment date and timezone for eligibility checks.
Legacy requests fail closed.

No authority is configured by default.
This endpoint does not authorize live booking.
"""

import os
import secrets

from datetime import date
from typing import Awaitable, Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/api/v1/geographic-eligibility",
    tags=["Geographic Eligibility"],
)


class EligibilityRequest(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=150)
    groomer_id: str = Field(min_length=1, max_length=150)
    customer_address: str = Field(min_length=5, max_length=500)

    # Optional at the API boundary for backward compatibility.
    # Missing values always produce an unavailable decision.
    appointment_date: date | None = None
    timezone_name: str | None = None


class EligibilityResponse(BaseModel):
    decision: Literal[
        "eligible",
        "ineligible",
        "unavailable",
    ]

    calendar_id: str
    groomer_id: str
    eligible: bool
    evidence_verified: bool
    reason: str


# Five-argument geographic authority contract.
Authority = Callable[
    [str, str, str, date, str],
    Awaitable[EligibilityResponse],
]


# Server-controlled authority integration.
# No authenticated authority is installed by default.
_authority: Authority | None = None


def configure_geographic_authority(
    authority: Authority | None,
):
    """Install an authority from trusted application startup code only."""
    global _authority
    _authority = authority


def unavailable_response(
    payload: EligibilityRequest,
    reason: str = "Verified geographic eligibility authority unavailable",
) -> EligibilityResponse:
    """Return a safe fail-closed eligibility response."""

    return EligibilityResponse(
        decision="unavailable",
        calendar_id=payload.calendar_id,
        groomer_id=payload.groomer_id,
        eligible=False,
        evidence_verified=False,
        reason=reason,
    )


@router.post(
    "/verify",
    response_model=EligibilityResponse,
)
async def verify_geographic_eligibility(
    payload: EligibilityRequest,
    x_geo_eligibility_key: str | None = Header(default=None),
):
    """Verify geographic eligibility without authorizing booking."""

    # Step 1: Authenticate the API caller.
    expected = os.getenv(
        "PETPILOT_GEO_ELIGIBILITY_API_KEY",
        "",
    )

    if (
        not expected
        or not x_geo_eligibility_key
        or not secrets.compare_digest(
            x_geo_eligibility_key,
            expected,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    # Step 2: Require an appointment date.
    if payload.appointment_date is None:
        return unavailable_response(
            payload,
            "Verified appointment date required",
        )

    # Step 3: Require a timezone.
    if (
        not isinstance(payload.timezone_name, str)
        or not payload.timezone_name.strip()
    ):
        return unavailable_response(
            payload,
            "Verified appointment timezone required",
        )

    # Step 4: Validate the timezone.
    try:
        ZoneInfo(payload.timezone_name)
    except (
        ZoneInfoNotFoundError,
        ValueError,
        TypeError,
    ):
        return unavailable_response(
            payload,
            "Invalid appointment timezone",
        )

    # Step 5: Require an installed server-side authority.
    if _authority is None:
        return unavailable_response(payload)

    # Step 6: Call the five-argument authority.
    try:
        result = await _authority(
            payload.calendar_id,
            payload.groomer_id,
            payload.customer_address,
            payload.appointment_date,
            payload.timezone_name,
        )
    except Exception:
        # Never expose internal authority failures.
        return unavailable_response(
            payload,
            "Geographic eligibility verification failed",
        )

    # Step 7: Validate the authority response type.
    if not isinstance(result, EligibilityResponse):
        return unavailable_response(
            payload,
            "Invalid geographic authority response",
        )

    # Step 8: Prevent cross-calendar or cross-groomer responses.
    if (
        result.calendar_id != payload.calendar_id
        or result.groomer_id != payload.groomer_id
    ):
        return unavailable_response(
            payload,
            "Geographic authority identity mismatch",
        )

    # Step 9: Reject contradictory eligibility decisions.
    if result.decision == "eligible":
        if (
            result.eligible is not True
            or result.evidence_verified is not True
        ):
            return unavailable_response(
                payload,
                "Contradictory eligibility evidence",
            )

    elif result.decision == "ineligible":
        if (
            result.eligible is not False
            or result.evidence_verified is not True
        ):
            return unavailable_response(
                payload,
                "Contradictory ineligibility evidence",
            )

    else:
        if (
            result.eligible is not False
            or result.evidence_verified is not False
        ):
            return unavailable_response(
                payload,
                "Contradictory unavailable evidence",
            )

    # This decision is informational only.
    # It must not authorize live booking.
    return result

