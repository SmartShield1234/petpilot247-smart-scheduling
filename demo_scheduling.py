
from datetime import datetime, timedelta, timezone
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from scheduling import (
    find_neighboring_appointments,
    evaluate_safe_groomer_booking,
)

router = APIRouter(prefix="/demo", tags=["Demo Scheduling"])

DEMO_GROOMERS = ("ambily", "john", "silpa")

SIMULATED_DEPOT_DRIVE_MINUTES = {
    "ambily": 20,
    "john": 30,
    "silpa": 15,
}


class DemoSchedulingRequest(BaseModel):
    requested_start: datetime
    service_minutes: int = Field(gt=0, le=480)


def require_demo_token(
    x_petpilot_dev_token: str | None = Header(default=None),
):
    expected = os.getenv("PETPILOT_DEV_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Demo token not configured")

    if not x_petpilot_dev_token or not secrets.compare_digest(
        x_petpilot_dev_token, expected
    ):
        raise HTTPException(401, "Unauthorized")


@router.post(
    "/recommend-groomers",
    dependencies=[Depends(require_demo_token)],
)
async def demo_recommend_groomers(request: DemoSchedulingRequest):
    if request.requested_start.tzinfo is None:
        raise HTTPException(
            422, "requested_start must contain a timezone"
        )

    # Allow only local development or an explicitly configured
    # Permit only development or isolated simulation mode.
    environment = os.getenv(
        "PETPILOT_ENV", ""
    ).strip().lower()

    if environment not in {"development", "demo"}:
        raise HTTPException(
            status_code=503,
            detail="Demo scheduling is disabled in this environment",
        )

    if os.getenv(
        "PETPILOT_LIVE_BOOKING_ENABLED", "false"
    ).strip().lower() != "false":
        raise HTTPException(
            status_code=503,
            detail="Live booking must remain disabled",
        )

    # Fictional appointments only. No GHL retrieval.
    start = request.requested_start

    appointments = [
        {
            "groomer_id": "john",
            "start_time": (
                start - timedelta(hours=2)
            ).isoformat(),
            "end_time": (
                start - timedelta(hours=1)
            ).isoformat(),
            "post_buffer_minutes": 15,
        },
        {
            "groomer_id": "john",
            "start_time": (
                start + timedelta(hours=3)
            ).isoformat(),
            "end_time": (
                start + timedelta(hours=4)
            ).isoformat(),
            "post_buffer_minutes": 15,
        },
    ]

    recommendations = []

    for groomer_id in DEMO_GROOMERS:
        neighbors = find_neighboring_appointments(
            groomer_id=groomer_id,
            requested_start=start,
            service_minutes=request.service_minutes,
            appointments=appointments,
        )

        result = evaluate_safe_groomer_booking(
            groomer_id=groomer_id,
            requested_start=start,
            service_minutes=request.service_minutes,
            appointments=appointments,
            depot_required=True,
            depot_drive_minutes=(
                SIMULATED_DEPOT_DRIVE_MINUTES[groomer_id]
            ),
            before_drive_minutes=(
    20 if neighbors.get("previous_appointment") else None
),
after_drive_minutes=(
    20 if neighbors.get("next_appointment") else None
),
        )

        recommendations.append(result)

    return {

        "mode": "simulation_only",
        "production_data_used": False,
        "booking_authorized": False,
        "appointment_sync_verified": False,
        "requested_start": start.isoformat(),
        "recommendations": recommendations,

    }
