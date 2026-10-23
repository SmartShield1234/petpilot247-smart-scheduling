
"""PetPilot247 PostgreSQL appointment reconciliation.

Development-safe comparison only.
No automatic synchronization approval.
No appointment creation or modification.
"""

import os
from datetime import datetime, timezone

import psycopg

from ghl_service import get_ghl_appointments
from ghl_historical_snapshot_adapter import map_ghl_historical_snapshot
from postgres_appointment_events import mark_postgres_sync_uncertain


FIELDS = (
    "calendar_id",
    "assigned_user_id",
    "contact_id",
    "appointment_status",
    "start_time",
    "end_time",
    "date_updated",
)


async def reconcile_postgres_appointments(
    *,
    connection_url,
    range_start,
    range_end,
    expected_calendar_ids,
):
    if os.getenv("PETPILOT_ENV", "").lower() != "development":
        raise RuntimeError("Development environment required")

    if os.getenv("PETPILOT_LIVE_BOOKING_ENABLED", "false").lower() != "false":
        raise RuntimeError("Live booking must remain disabled")

    if not isinstance(range_start, datetime) or not isinstance(range_end, datetime):
        raise ValueError("Valid reconciliation range required")

    if (
        range_start.tzinfo is None
        or range_end.tzinfo is None
        or range_start >= range_end
    ):
        raise ValueError("Invalid reconciliation date range")

    try:
        result = get_ghl_appointments(
            range_start=range_start,
            range_end=range_end,
        )

        if hasattr(result, "__await__"):
            result = await result

        checked = result.get("checked_calendar_ids")
        events = result.get("events")

        expected = set(expected_calendar_ids)

        if (
            not isinstance(checked, list)
            or not isinstance(events, list)
            or len(checked) != len(expected)
            or set(checked) != expected
        ):
            raise RuntimeError("Incomplete calendar coverage")

        fresh = {}

        for event in events:
            item = map_ghl_historical_snapshot(event)
            identity = (item["location_id"], item["appointment_id"])

            if identity in fresh:
                raise RuntimeError("Duplicate GHL appointment identity")

            fresh[identity] = item

        with psycopg.connect(
            connection_url,
            sslmode="require",
            connect_timeout=15,
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT location_id, appointment_id,
                           calendar_id, assigned_user_id,
                           contact_id, appointment_status,
                           start_time, end_time, date_updated,
                           is_deleted
                    FROM appointments
                    """
                )

                rows = cursor.fetchall()

        # Compare current records by identity.
        stored = {}
        all_stored = {}

        for row in rows:
            record = dict(zip(FIELDS, row[2:9]))
            record["is_deleted"] = row[9]
            identity = (row[0], row[1])
            all_stored[identity] = record

            try:
                start = datetime.fromisoformat(
                    record["start_time"].replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(
                    record["end_time"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError, AttributeError):
                raise RuntimeError("Invalid stored appointment time")

            if start.tzinfo is None or end.tzinfo is None:
                raise RuntimeError("Timezone-aware appointment required")

            # Match appointments overlapping the requested window.
            if start < range_end and end > range_start:
                stored[(row[0], row[1])] = record

        missing = set(fresh) - set(all_stored)
        no_longer_returned = set(stored) - set(fresh)

        deleted_conflicts = {
            identity
            for identity in set(fresh) & set(all_stored)
            if all_stored[identity]["is_deleted"]
        }

        changed = {
            identity
            for identity in set(fresh) & set(all_stored)
            if any(
                fresh[identity][field] != all_stored[identity][field]
                for field in FIELDS
            )
        }

        if missing or changed or no_longer_returned or deleted_conflicts:
            mark_postgres_sync_uncertain(
                connection_url=connection_url,
                reason="GHL appointment reconciliation differences",
            )

        return {
            "calendars_checked": len(checked),
            "fresh_appointments": len(fresh),
            "missing_locally": len(missing),
            "changed_records": len(changed),
            "no_longer_returned": len(no_longer_returned),
            "deleted_conflicts": len(deleted_conflicts),
            "reconciliation_matches": not (
                missing or changed or no_longer_returned or deleted_conflicts
            ),
            "synchronization_verified": False,
            "booking_authorized": False,
        }

    except Exception:
        mark_postgres_sync_uncertain(
            connection_url=connection_url,
            reason="PostgreSQL appointment reconciliation failed",
        )
        raise


def apply_guarded_snapshot_recovery(
    *,
    connection_url,
    snapshots,
    expected_calendar_ids,
    expected_event_checkpoint=None,
    trusted_recovery=False,
):
    """Apply independently retrieved GHL records conservatively.

    Does not verify sync, delete absent records, or authorize booking.
    Caller must separately verify GHL calendar coverage.
    """
    from datetime import datetime, timezone

    from psycopg import sql

    environment = os.getenv(
        "PETPILOT_ENV", ""
    ).strip().lower()

    if environment == "development":
        pass
    elif environment == "production":
        if not trusted_recovery:
            raise RuntimeError(
                "Production recovery requires trusted GHL retrieval"
            )
        if expected_event_checkpoint is None:
            raise RuntimeError(
                "Production recovery requires event checkpoint"
            )
    else:
        raise RuntimeError("Unsupported recovery environment")

    if os.getenv("PETPILOT_LIVE_BOOKING_ENABLED", "false").strip().lower() != "false":
        raise RuntimeError("Live booking must remain disabled")

    if not isinstance(snapshots, list):
        raise ValueError("Validated snapshot list required")

    allowed = set(expected_calendar_ids)
    if len(allowed) != 11:
        raise ValueError("Expected 11 unique calendar IDs")

    columns = (
        "location_id", "appointment_id", "calendar_id",
        "assigned_user_id", "contact_id", "appointment_status",
        "start_time", "end_time", "date_updated", "is_deleted", "source",
    )

    def revision(value):
        if not isinstance(value, str):
            raise ValueError("Invalid revision")
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("Timezone-aware revision required")
        return result.astimezone(timezone.utc)

    prepared = {}
    for item in snapshots:
        if not isinstance(item, dict):
            raise ValueError("Invalid snapshot")

        identity = (item.get("location_id"), item.get("appointment_id"))
        if not all(isinstance(x, str) and x.strip() for x in identity):
            raise ValueError("Invalid appointment identity")

        if identity in prepared:
            raise ValueError("Duplicate appointment identity")

        if item.get("calendar_id") not in allowed:
            raise ValueError("Unexpected calendar")

        for field in ("start_time", "end_time", "date_updated"):
            revision(item.get(field))

        if revision(item["end_time"]) <= revision(item["start_time"]):
            raise ValueError("Invalid appointment duration")

        prepared[identity] = item

    inserted = 0
    updated = 0
    identical = 0

    with psycopg.connect(
        connection_url, sslmode="require", connect_timeout=15
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cursor:
                # Exclude concurrent webhook writers during
                # the database recovery transaction.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (247777,),
                )
                if expected_event_checkpoint is not None:
                    cursor.execute(
                        "SELECT COUNT(*), COALESCE(MAX(event_log_id), 0) "
                        "FROM appointment_event_log"
                    )
                    current_checkpoint = tuple(cursor.fetchone())

                    if current_checkpoint != expected_event_checkpoint:
                        raise RuntimeError(
                            "Webhook event log changed during GHL retrieval"
                        )


                cursor.execute(
                    "SELECT status FROM appointment_sync_health "
                    "WHERE id = 1 FOR UPDATE"
                )
                health = cursor.fetchone()

                if health is None or health[0] == "verified":
                    raise RuntimeError("Recovery requires unverified sync")

                for identity, item in sorted(prepared.items()):
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (identity[0] + ":" + identity[1],),
                    )
                    cursor.execute(
                        "SELECT * FROM appointments "
                        "WHERE location_id = %s AND appointment_id = %s "
                        "FOR UPDATE",
                        identity,
                    )
                    existing = cursor.fetchone()

                    if existing is None:
                        values = [
                            item.get(field)
                            if field not in ("is_deleted", "source")
                            else (0 if field == "is_deleted"
                                  else "api_reconciliation")
                            for field in columns
                        ]
                        cursor.execute(
                            sql.SQL("INSERT INTO appointments ({}) VALUES ({})").format(
                                sql.SQL(", ").join(map(sql.Identifier, columns)),
                                sql.SQL(", ").join(
                                    sql.Placeholder() for _ in columns
                                ),
                            ),
                            values,
                        )
                        inserted += 1
                        continue

                    cursor.execute(
                        "SELECT calendar_id, assigned_user_id, contact_id, "
                        "appointment_status, start_time, end_time, "
                        "date_updated, is_deleted "
                        "FROM appointments "
                        "WHERE location_id = %s AND appointment_id = %s",
                        identity,
                    )
                    old = cursor.fetchone()
                    if old[7]:
                        raise RuntimeError("Deleted appointment needs review")

                    incoming_rev = revision(item["date_updated"])
                    stored_rev = revision(old[6])

                    if incoming_rev < stored_rev:
                        raise RuntimeError("GHL snapshot older than ledger")

                    new_values = tuple(item.get(field) for field in (
                        "calendar_id", "assigned_user_id", "contact_id",
                        "appointment_status", "start_time", "end_time",
                        "date_updated",
                    ))

                    if incoming_rev == stored_rev:
                        if new_values != old[:7]:
                            raise RuntimeError("Conflicting same-revision data")
                        identical += 1
                        continue

                    cursor.execute(
                        """
                        UPDATE appointments
                        SET calendar_id = %s,
                            assigned_user_id = %s,
                            contact_id = %s,
                            appointment_status = %s,
                            start_time = %s,
                            end_time = %s,
                            date_updated = %s,
                            source = 'api_reconciliation'
                        WHERE location_id = %s AND appointment_id = %s
                        """,
                        (*new_values, *identity),
                    )
                    cursor.execute(
                        "DELETE FROM service_address_confirmations "
                        "WHERE location_id = %s AND appointment_id = %s",
                        identity,
                    )
                    updated += 1

                cursor.execute(
                    """
                    UPDATE appointment_sync_health
                    SET status = 'uncertain',
                        reason = 'Recovery applied; webhook continuity unverified',
                        last_reconciled_at = NULL,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (datetime.now(timezone.utc).isoformat(),),
                )

    return {
        "inserted": inserted,
        "updated": updated,
        "identical": identical,
        "synchronization_verified": False,
        "booking_authorized": False,
    }




async def recover_from_verified_ghl_snapshot(
    *,
    connection_url,
    range_start,
    range_end,
    expected_calendar_ids,
):
    """Retrieve and reconcile verified GHL calendar coverage.

    Remains fail-closed. Does not authorize live bookings.
    """
    import inspect

    expected = set(expected_calendar_ids)

    if len(expected) != 11:
        raise ValueError("Expected 11 unique calendars")

    try:
        with psycopg.connect(
            connection_url, sslmode="require", connect_timeout=15
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*), COALESCE(MAX(event_log_id), 0) "
                    "FROM appointment_event_log"
                )
                event_checkpoint = tuple(cursor.fetchone())
        result = get_ghl_appointments(
            range_start=range_start,
            range_end=range_end,
        )

        if inspect.isawaitable(result):
            result = await result

        if not isinstance(result, dict):
            raise RuntimeError("Invalid GHL response")

        checked = result.get("checked_calendar_ids")
        events = result.get("events")

        if (
            not isinstance(checked, list)
            or not isinstance(events, list)
            or len(checked) != len(expected)
            or set(checked) != expected
        ):
            raise RuntimeError("Incomplete calendar coverage")

        snapshots = [
            map_ghl_historical_snapshot(event)
            for event in events
        ]

        recovery = apply_guarded_snapshot_recovery(
            connection_url=connection_url,
            snapshots=snapshots,
            expected_calendar_ids=expected,
            expected_event_checkpoint=event_checkpoint,
            trusted_recovery=True,
        )

        return {
            **recovery,
            "calendars_checked": len(checked),
            "snapshot_count": len(snapshots),
            "synchronization_verified": False,
            "booking_authorized": False,
        }

    except Exception:
        mark_postgres_sync_uncertain(
            connection_url=connection_url,
            reason="GHL snapshot recovery failed or incomplete",
        )
        raise
