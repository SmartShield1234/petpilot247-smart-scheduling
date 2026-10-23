"""PetPilot247 integrated demo and PostgreSQL webhook application."""

import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request

from petpilot247_demo_app import app as demo_app
from ghl_webhook_receiver import prepare_verified_appointment_event
from postgres_appointment_events import (
    record_postgres_appointment_event,
    mark_postgres_sync_uncertain,
)


def require_postgres_config():
    if os.getenv("PETPILOT_ENV", "").strip().lower() != "production":
        raise RuntimeError("Production environment required")

    if os.getenv(
        "PETPILOT_LIVE_BOOKING_ENABLED", ""
    ).strip().lower() != "false":
        raise RuntimeError("Live booking must remain disabled")

    url = os.getenv("PETPILOT_POSTGRES_URL", "").strip()

    if not url:
        raise RuntimeError("PostgreSQL connection missing")

    return url


@asynccontextmanager
async def lifespan(app: FastAPI):
    url = require_postgres_config()

    with psycopg.connect(
        url, sslmode="require", connect_timeout=15
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM appointment_sync_health WHERE id = 1"
            )

            if cursor.fetchone() is None:
                raise RuntimeError(
                    "Synchronization metadata not initialized"
                )

    yield


app = FastAPI(
    title="PetPilot247 Integrated Backend",
    lifespan=lifespan,
)


@app.post("/webhooks/ghl/appointments")
async def receive_ghl_postgres_webhook(
    request: Request,
    x_ghl_signature: str | None = Header(default=None),
):
    try:
        url = require_postgres_config()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Webhook backend unavailable",
        ) from exc

    raw_body = await request.body()

    if len(raw_body) > 64 * 1024:
        raise HTTPException(413, "Webhook body too large")

    expected_location = os.getenv(
        "GHL_LOCATION_ID", ""
    ).strip()

    if not expected_location:
        raise HTTPException(503, "GHL location not configured")

    validated = prepare_verified_appointment_event(
        raw_body=raw_body,
        signature=x_ghl_signature,
        expected_location_id=expected_location,
    )

    try:
        result = record_postgres_appointment_event(
            connection_url=url,
            validated_event=validated,
        )

    except Exception as exc:
        try:
            mark_postgres_sync_uncertain(
                connection_url=url,
                reason="Unresolved authenticated GHL appointment event",
            )
        except Exception:
            raise HTTPException(
                503,
                "Appointment persistence and sync-health failure",
            ) from exc

        raise HTTPException(
            503,
            "Appointment reconciliation required",
        ) from exc

    return {"status": result}



@app.post("/internal/reconcile-appointments")
async def run_appointment_reconciliation(
    x_reconciliation_key: str | None = Header(default=None),
):
    """Protected development recovery endpoint."""

    import asyncio
    import secrets
    from datetime import datetime, timedelta, timezone

    from postgres_appointment_reconciliation import (
        recover_from_verified_ghl_snapshot,
    )

    expected_key = os.getenv(
        "PETPILOT_RECONCILIATION_API_KEY", ""
    ).strip()

    if not expected_key:
        raise HTTPException(503, "Reconciliation not configured")

    if not x_reconciliation_key or not secrets.compare_digest(
        x_reconciliation_key, expected_key
    ):
        raise HTTPException(401, "Unauthorized")

    if os.getenv("PETPILOT_ENV", "").lower() != "production":
        raise HTTPException(503, "Production environment required")

    if os.getenv(
        "PETPILOT_LIVE_BOOKING_ENABLED", "false"
    ).lower() != "false":
        raise HTTPException(503, "Live booking must remain disabled")

    url = os.getenv("PETPILOT_POSTGRES_URL", "").strip()

    calendars = [
        item.strip()
        for item in os.getenv(
            "GHL_SCHEDULING_CALENDAR_IDS", ""
        ).split(",")
        if item.strip()
    ]

    if not url or len(calendars) != 11:
        raise HTTPException(503, "Recovery configuration incomplete")

    # Global PostgreSQL advisory lock prevents simultaneous
    # recovery runs across different service instances.
    lock_connection = psycopg.connect(
        url,
        sslmode="require",
        connect_timeout=15,
        autocommit=True,
    )

    lock_id = 247775

    try:
        with lock_connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (lock_id,),
            )
            acquired = cursor.fetchone()[0]

        if not acquired:
            raise HTTPException(
                409, "Another reconciliation is running"
            )

        # Fetch current GHL appointments through the
        # configured GHL service, then apply guarded recovery.
        now = datetime.now(timezone.utc)

        result = await recover_from_verified_ghl_snapshot(
            connection_url=url,
            range_start=now - timedelta(days=7),
            range_end=now + timedelta(days=30),
            expected_calendar_ids=calendars,
        )

        return {
            "status": "reconciliation_completed",
            **result,
            "synchronization_verified": False,
            "booking_authorized": False,
        }

    finally:
        try:
            with lock_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (lock_id,),
                )
        finally:
            lock_connection.close()


# Preserve the existing demo routes.
app.mount("/", demo_app)
