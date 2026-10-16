
import json
import os
import sqlite3


from fastapi import HTTPException
from appointment_sync_health import mark_sync_uncertain
from ghl_webhook_security import verify_ghl_webhook_signature
from ghl_webhook_validation import validate_appointment_webhook
from appointment_ledger import (
    DATABASE_PATH,
    record_appointment_create,
    record_appointment_update,
    record_appointment_delete,
)

MAX_WEBHOOK_BODY_BYTES = 64 * 1024


def prepare_verified_appointment_event(
    raw_body: bytes,
    signature: str | None,
    expected_location_id: str | None = None,
):
    """
    Authenticate and validate a GHL appointment webhook.

    No database writes.
    No GHL API calls.
    No live booking operations.
    """

    if not isinstance(raw_body, bytes):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook request body",
        )

    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Webhook payload too large",
        )

    if not verify_ghl_webhook_signature(raw_body, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    location_id = (
        expected_location_id
        if expected_location_id is not None
        else os.getenv("GHL_LOCATION_ID", "")
    )

    if not isinstance(location_id, str) or not location_id.strip():
        raise HTTPException(
            status_code=503,
            detail="Expected GHL location not configured",
        )

    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook JSON",
        ) from exc

    try:
        return validate_appointment_webhook(
            payload,
            expected_location_id=location_id,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid appointment webhook data",
        ) from exc



def process_verified_appointment_webhook(
    raw_body: bytes,
    signature: str | None,
    expected_location_id: str | None = None,
    db_path=DATABASE_PATH,
):
    """
    Authenticate, validate, and store one appointment webhook.

    Development-only integration.
    No public HTTP endpoint or external API requests.
    """

    # Never permit this development processor in production.
    if os.getenv("PETPILOT_ENV", "").strip().lower() != "development":
        raise HTTPException(
            status_code=503,
            detail="Development webhook processor is disabled",
        )

    if os.getenv(
        "PETPILOT_LIVE_BOOKING_ENABLED", "false"
    ).strip().lower() != "false":
        raise HTTPException(
            status_code=503,
            detail="Live booking must remain disabled",
        )

    # Signature verification and structural validation happen first.
    validated = prepare_verified_appointment_event(
        raw_body=raw_body,
        signature=signature,
        expected_location_id=expected_location_id,
    )

    event_type = validated["event_type"]

    try:
        if event_type == "AppointmentCreate":
            result = record_appointment_create(
                validated,
                db_path=db_path,
            )
        elif event_type == "AppointmentUpdate":
            result = record_appointment_update(
                validated,
                db_path=db_path,
            )
        elif event_type == "AppointmentDelete":
            result = record_appointment_delete(
                validated,
                db_path=db_path,
            )
        else:
            raise ValueError("Unsupported appointment event")

    except (ValueError, TypeError) as exc:
        try:
            mark_sync_uncertain(
                "Unresolved appointment webhook event",
                db_path=db_path,
            )
        except (ValueError, sqlite3.Error) as health_exc:
            raise HTTPException(
                status_code=503,
                detail="Appointment synchronization health unavailable",
            ) from health_exc

        raise HTTPException(
            status_code=409,
            detail="Appointment reconciliation required",
        ) from exc
    except sqlite3.Error as exc:
        # Storage failed. Never treat this event as accepted.
        try:
            mark_sync_uncertain(
                "Appointment webhook storage failure",
                db_path=db_path,
            )
        except (sqlite3.Error, ValueError, TypeError):
            # Health may be unavailable because the database failed.
            # Still reject the webhook without exposing database details.
            pass

        raise HTTPException(
            status_code=503,
            detail="Appointment storage unavailable; reconciliation required",
        ) from exc
    return {
        "status": result,
        "event_type": event_type,
        "appointment_id": validated["appointment_id"],
    }
