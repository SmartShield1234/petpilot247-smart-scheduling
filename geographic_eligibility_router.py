
"""Authenticated geographic eligibility API for PetPilot247.

The geographic authority must be installed by trusted server code.
Never accept eligibility approvals or trusted-source flags from clients.

No authority is configured by default, so the API fails closed.
"""

import os
import secrets
from typing import Awaitable, Callable, Literal

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


class EligibilityResponse(BaseModel):
    decision: Literal["eligible", "ineligible", "unavailable"]
    calendar_id: str
    groomer_id: str
    eligible: bool
    evidence_verified: bool
    reason: str


Authority = Callable[
    [str, str, str],
    Awaitable[EligibilityResponse],
]

# Server-controlled integration hook.
# No real authority has been installed.
_authority: Authority | None = None


def configure_geographic_authority(authority: Authority | None):
    """Install an authority from trusted application startup code only."""
    global _authority
    _authority = authority


def unavailable_response(
    payload: EligibilityRequest,
    reason: str = "Verified geographic eligibility authority unavailable",
) -> EligibilityResponse:
    return EligibilityResponse(
        decision="unavailable",
        calendar_id=payload.calendar_id,
        groomer_id=payload.groomer_id,
        eligible=False,
        evidence_verified=False,
        reason=reason,
    )


@router.post("/verify", response_model=EligibilityResponse)
async def verify_geographic_eligibility(
    payload: EligibilityRequest,
    x_geo_eligibility_key: str | None = Header(default=None),
):
    expected = os.getenv("PETPILOT_GEO_ELIGIBILITY_API_KEY", "")

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

    # No authority: fail closed.
    if _authority is None:
        return unavailable_response(payload)

    try:
        result = await _authority(
            payload.calendar_id,
            payload.groomer_id,
            payload.customer_address,
        )
    except Exception:
        # Do not disclose internal service failures to callers.
        return unavailable_response(
            payload,
            "Geographic eligibility verification failed",
        )

    if not isinstance(result, EligibilityResponse):
        return unavailable_response(
            payload,
            "Invalid geographic authority response",
        )

    # Prevent responses for another groomer or calendar.
    if (
        result.calendar_id != payload.calendar_id
        or result.groomer_id != payload.groomer_id
    ):
        return unavailable_response(
            payload,
            "Geographic authority identity mismatch",
        )

    # Reject contradictory decision flags.
    if result.decision == "eligible":
        if result.eligible is not True:
            return unavailable_response(payload)
        if result.evidence_verified is not True:
            return unavailable_response(payload)

    elif result.decision == "ineligible":
        if result.eligible is not False:
            return unavailable_response(payload)
        if result.evidence_verified is not True:
            return unavailable_response(payload)

    else:
        if result.eligible is not False:
            return unavailable_response(payload)
        if result.evidence_verified is not False:
            return unavailable_response(payload)

    return result
