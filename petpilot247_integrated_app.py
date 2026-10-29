"""PetPilot247 integrated demo and PostgreSQL webhook application."""

import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request

from pavi_recommendation_router import router as pavi_router
from geographic_eligibility_router import router as geographic_router

from petpilot247_ghl_oauth import router as oauth_router
from petpilot247_ghl_oauth import initialize_oauth_tables

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
    initialize_oauth_tables(connection_url=url)
    yield



app = FastAPI(
    title="PetPilot247 Integrated Backend",
    lifespan=lifespan,
)

app.include_router(pavi_router)
app.include_router(geographic_router)
app.include_router(oauth_router)



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




# Internal operational readiness inspection. This is NOT a booking or
# customer-facing recommendations endpoint. An authenticated status report
# cannot be used as authorization to override safety requirements.
@app.get("/internal/scheduling/readiness")
async def scheduling_readiness(
    x_reconciliation_key: str | None = Header(default=None),
):
    import secrets
    import json
    from pathlib import Path

    key = os.getenv("PETPILOT_RECONCILIATION_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Readiness authentication not configured")
    if not x_reconciliation_key or not secrets.compare_digest(x_reconciliation_key, key):
        raise HTTPException(401, "Unauthorized")

    if (os.getenv("PETPILOT_ENV", "").strip().lower() != "production"
            or os.getenv("PETPILOT_LIVE_BOOKING_ENABLED", "").strip().lower() != "false"):
        raise HTTPException(503, "Unsafe environment configuration")

    url = require_postgres_config()
    try:
        with psycopg.connect(url, sslmode="require", connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM appointment_sync_health WHERE id = 1")
                row = cur.fetchone()
        sync_status = row[0] if row else "missing"
    except Exception:
        raise HTTPException(503, "Appointment synchronization status unavailable")

    calendar_ids = [x.strip() for x in os.getenv("GHL_SCHEDULING_CALENDAR_IDS", "").split(",") if x.strip()]
    inventory_path = Path(__file__).with_name("ghl_grooming_staff_inventory.json")
    inventory_valid = False
    inventory_calendars = 0
    approved_calendars = 0
    if inventory_path.is_file():
        try:
            data = json.loads(inventory_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                ids = [item.get("calendar_id") for item in data if isinstance(item, dict)]
                inventory_valid = len(ids) == len(data) and len(set(ids)) == len(ids) and all(isinstance(x, str) and x for x in ids)
                if inventory_valid:
                    inventory_calendars = len(data)
                    approved_calendars = sum(
                        item.get("approved_for_mobile_grooming") is True
                        and item.get("geographic_eligibility_verified") is True
                        for item in data
                    )
        except (ValueError, OSError, TypeError):
            pass

    return {
        "service": "petpilot247-scheduling-readiness",
        "sync_status": sync_status,
        "synchronization_verified": False,
        "calendar_configuration_valid": len(calendar_ids) == 11 and len(set(calendar_ids)) == 11,
        "grooming_inventory_present_and_valid": inventory_valid,
        "grooming_calendar_count": inventory_calendars,
        "inventory_flagged_approved_calendars": approved_calendars,
        "eligibility_source_authenticated": False,
        "customer_recommendations_available": False,
        "booking_authorized": False,
        "reason": "Authoritative eligibility, full synchronization, and booking authorization pending",
    }


@app.post("/api/scheduling/recommendations")
async def guarded_recommendations(request: Request):
    # Never accept client-provided approval, geographic decisions or route
    # evidence as authorization. No production-safe recommendation pipeline
    # is present in the uploaded source, so this endpoint fails closed.
    if os.getenv("PETPILOT_LIVE_BOOKING_ENABLED", "").strip().lower() != "false":
        raise HTTPException(503, "Booking safety guard unavailable")
    raise HTTPException(503, "Authoritative scheduling eligibility and synchronization not yet verified")


@app.post("/api/scheduling/book")
async def guarded_booking(request: Request):
    # No customer booking until final GHL availability check, durable lock,
    # trusted result verification and business authorization are integrated.
    raise HTTPException(503, "Live booking not authorized")




@app.get("/internal/scheduling/ghl-availability")
async def read_only_ghl_availability(
    calendar_id: str,
    days: int = 3,
    x_reconciliation_key: str | None = Header(default=None),
):
    """Protected live GHL free-slot DIAGNOSTIC, not a recommendation or booking.

    Staff IDs come only from the deployed inventory; responses contain counts,
    never customer details or raw availability timestamps. An available GHL
    start time does not establish a valid travel-aware mobile grooming slot.
    """
    import json
    import secrets
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    import httpx

    expected = os.getenv("PETPILOT_RECONCILIATION_API_KEY", "").strip()
    if not expected:
        raise HTTPException(503, "Integration authentication not configured")
    if not x_reconciliation_key or not secrets.compare_digest(x_reconciliation_key, expected):
        raise HTTPException(401, "Unauthorized")

    if (os.getenv("PETPILOT_ENV", "").strip().lower() != "production"
            or os.getenv("PETPILOT_LIVE_BOOKING_ENABLED", "").strip().lower() != "false"):
        raise HTTPException(503, "Unsafe environment")
    if not 1 <= days <= 7 or not calendar_id.strip():
        raise HTTPException(422, "Calendar ID and 1-7 days required")

    configured = [x.strip() for x in os.getenv("GHL_SCHEDULING_CALENDAR_IDS", "").split(",") if x.strip()]
    if len(configured) != 11 or len(set(configured)) != 11 or calendar_id not in configured:
        raise HTTPException(422, "Calendar is not in complete configured inventory")

    inventory = Path(__file__).with_name("ghl_grooming_staff_inventory.json")
    try:
        records = json.loads(inventory.read_text(encoding="utf-8"))
        if not isinstance(records, list) or len(records) != 4:
            raise ValueError("Invalid grooming inventory")
        matches = [x for x in records if isinstance(x, dict) and x.get("calendar_id") == calendar_id]
        if len(matches) != 1:
            raise ValueError("Unknown grooming calendar")
        record = matches[0]
        ids = record["ghl_user_ids"]
        if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                or any(not isinstance(x, str) or not x.strip() for x in ids)):
            raise ValueError("Invalid user IDs")
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Grooming staff inventory unavailable")

    token = os.getenv("GHL_API_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "GHL read credentials unavailable")
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": os.getenv("GHL_API_VERSION", "2021-07-28"),
        "Accept": "application/json",
    }
    # Parse validated GHL responses, but do not infer full service-duration coverage.
    from ghl_free_slot_parser import parse_ghl_free_slots
    counts = []
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            for uid in ids:
                resp = await client.get(
                    f"https://services.leadconnectorhq.com/calendars/{calendar_id}/free-slots",
                    headers=headers,
                    params={
                        "startDate": int(start.timestamp() * 1000),
                        "endDate": int(end.timestamp() * 1000),
                        "timezone": "America/New_York",
                        "userId": uid,
                    },
                )
                resp.raise_for_status()
                parsed = parse_ghl_free_slots(resp.json())
                counts.append({"ghl_user_id": uid, "free_start_count": parsed["total_slots"]})
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "GHL availability retrieval failed")

    return {
        "calendar_id": calendar_id,
        "days_queried": days,
        "staff_counts": counts,
        "source": "ghl_free_slots_read_only",
        "verification_status": "free_slots_only",
        "geographic_eligibility_authenticated": False,
        "synchronization_verified": False,
        "customer_recommendations_available": False,
        "booking_authorized": False,
    }


# Preserve the existing demo routes.
app.mount("/", demo_app)
