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
