
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request, Header, HTTPException
from ghl_webhook_receiver import prepare_verified_appointment_event

import sqlite3

from appointment_ledger import (
    record_appointment_create,
    record_appointment_update,
    record_appointment_delete,
)

from appointment_ledger import initialize_appointment_ledger

from appointment_sync_health import (
    initialize_sync_health,
    mark_sync_uncertain,
)


app = FastAPI(
    title="PetPilot247 Production Integration",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def check_production_configuration():
    if os.getenv("PETPILOT_ENV", "").strip().lower() != "production":
        raise RuntimeError("Production environment required")

    if os.getenv(
        "PETPILOT_LIVE_BOOKING_ENABLED", ""
    ).strip().lower() != "false":
        raise RuntimeError("Live booking must be disabled")

    database_value = os.getenv("PETPILOT_DATABASE_PATH", "").strip()

    if not database_value:
        raise RuntimeError("Persistent database path not configured")

    database = Path(database_value)

    if not database.is_absolute():
        raise RuntimeError("Database path must be absolute")

    # Initial deployment uses a persistent Render disk at /var/data.
    persistent_directory = Path("/var/data")
    if not database.is_relative_to(persistent_directory):
        raise RuntimeError("Database must be on persistent storage")

    if not persistent_directory.is_dir():
        raise RuntimeError("Persistent storage is not mounted")

    if not os.access(persistent_directory, os.W_OK):
        raise RuntimeError("Persistent storage is not writable")



@app.on_event("startup")
def startup_checks():
    # Reject unsafe production configuration first.
    check_production_configuration()

    # Use the explicitly configured persistent database.
    database_path = Path(
        os.environ["PETPILOT_DATABASE_PATH"]
    ).resolve()

    # Initialize tables without deleting existing records.
    initialize_appointment_ledger(
        db_path=database_path
    )

    initialize_sync_health(
        db_path=database_path
    )

    # Never automatically mark synchronization as verified.



@app.get("/health")
def health():
    return {
        "status": "running",
        "service": "PetPilot247 Production Integration",
        "live_booking_enabled": False,
        "appointment_sync_verified": False,
    }


@app.post("/webhooks/ghl/appointments")
async def receive_production_appointment_webhook(
    request: Request,
    x_ghl_signature: str | None = Header(default=None),
):
    # Production validation-only stage.
    # No appointment records are written.
    # Do not treat this response as webhook delivery completion.

    
    try:
        check_production_configuration()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Production webhook service unavailable",
        ) from exc


    expected_location_id = os.getenv(
        "GHL_LOCATION_ID", ""
    ).strip()

    if not expected_location_id:
        raise HTTPException(
            status_code=503,
            detail="GHL location not configured",
        )

    content_length = request.headers.get("content-length")

    if content_length:
        try:
            if int(content_length) > 64 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail="Webhook payload too large",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid content length",
            )

    raw_body = await request.body()

    if len(raw_body) > 64 * 1024:
        raise HTTPException(
            status_code=413,
            detail="Webhook payload too large",
        )

    validated = prepare_verified_appointment_event(
        raw_body=raw_body,
        signature=x_ghl_signature,
        expected_location_id=expected_location_id,
    )


    database_path = Path(
        os.environ["PETPILOT_DATABASE_PATH"]
    ).resolve()

    event_type = validated["event_type"]

    try:
        if event_type == "AppointmentCreate":
            result = record_appointment_create(
                validated,
                db_path=database_path,
            )

        elif event_type == "AppointmentUpdate":
            result = record_appointment_update(
                validated,
                db_path=database_path,
            )

        elif event_type == "AppointmentDelete":
            result = record_appointment_delete(
                validated,
                db_path=database_path,
            )

        else:
            raise ValueError("Unsupported appointment event")

    except (ValueError, TypeError) as exc:
        try:
            mark_sync_uncertain(
                "Unresolved production appointment event",
                db_path=database_path,
            )
        except (ValueError, sqlite3.Error):
            pass

        raise HTTPException(
            status_code=409,
            detail="Appointment reconciliation required",
        ) from exc

    except sqlite3.Error as exc:
        try:
            mark_sync_uncertain(
                "Production appointment storage failure",
                db_path=database_path,
            )
        except (ValueError, sqlite3.Error):
            pass

        raise HTTPException(
            status_code=503,
            detail="Appointment storage unavailable",
        ) from exc

    if result not in {
        "created",
        "updated",
        "deleted",
        "duplicate_ignored",
    }:
        raise HTTPException(
            status_code=503,
            detail="Unexpected appointment storage result",
        )

    return {
        "status": result,
    }

