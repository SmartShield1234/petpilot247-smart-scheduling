@'
"""PetPilot247 Step 3D verified snapshot assembly."""

from collections.abc import Mapping
from pavi_recommendation_pipeline import Snapshot
from pavi_slot_validator import Appointment
from pavi_postgres_snapshot_reader import _aware, SnapshotEvidenceError


def assemble_verified_snapshot(
    *,
    appointment_rows,
    groomer_ids,
    expected_calendar_ids,
    sync_evidence,
    address_evidence,
):
    if not isinstance(sync_evidence, Mapping):
        raise SnapshotEvidenceError("Missing sync evidence")

    calendars = tuple(expected_calendar_ids)

    if (
        len(calendars) != 11
        or len(set(calendars)) != 11
        or any(not isinstance(c, str) or not c.strip() for c in calendars)
    ):
        raise SnapshotEvidenceError("Invalid calendar coverage")

    if (
        sync_evidence.get("sync_verified") is not True
        or sync_evidence.get("complete_all_calendars") is not True
        or set(sync_evidence.get("calendar_ids", ())) != set(calendars)
    ):
        raise SnapshotEvidenceError("Synchronization unverified")

    checkpoint = sync_evidence.get("checkpoint")
    if not isinstance(checkpoint, str) or not checkpoint.strip():
        raise SnapshotEvidenceError("Missing checkpoint")

    if not isinstance(appointment_rows, Mapping):
        raise SnapshotEvidenceError("Missing appointment evidence")

    if appointment_rows.get("checkpoint") != checkpoint:
        raise SnapshotEvidenceError("Checkpoint mismatch")

    rows = appointment_rows.get("appointments")
    if not isinstance(rows, (list, tuple)):
        raise SnapshotEvidenceError("Invalid appointments")

    if not isinstance(address_evidence, Mapping):
        raise SnapshotEvidenceError("Missing address evidence")

    ids = tuple(groomer_ids)

    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not isinstance(g, str) or not g.strip() for g in ids)
    ):
        raise SnapshotEvidenceError("Invalid groomer inventory")

    grouped = {g: [] for g in ids}
    seen = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise SnapshotEvidenceError("Invalid appointment row")

        appointment_id = row.get("appointment_id")
        groomer_id = row.get("groomer_id")
        calendar_id = row.get("calendar_id")

        if not isinstance(appointment_id, str) or not appointment_id.strip():
            raise SnapshotEvidenceError("Missing appointment ID")

        if appointment_id in seen:
            raise SnapshotEvidenceError("Duplicate appointment ID")
        seen.add(appointment_id)

        if groomer_id not in grouped:
            raise SnapshotEvidenceError("Unknown groomer")

        if calendar_id not in calendars:
            raise SnapshotEvidenceError("Unknown calendar")

        if row.get("is_deleted") is True:
            raise SnapshotEvidenceError("Deleted appointment requires reconciliation")

        if row.get("status") not in ("confirmed", "booked"):
            raise SnapshotEvidenceError("Unverified appointment status")

        address = address_evidence.get(appointment_id)

        if not isinstance(address, Mapping):
            raise SnapshotEvidenceError("Missing confirmed address")

        if (
            address.get("confirmed") is not True
            or address.get("checkpoint") != checkpoint
            or address.get("calendar_id") != calendar_id
            or address.get("appointment_id") != appointment_id
            or address.get("date_updated") != row.get("date_updated")
        ):
            raise SnapshotEvidenceError("Address evidence mismatch")

        service_address = address.get("address")

        if not isinstance(service_address, str) or not service_address.strip():
            raise SnapshotEvidenceError("Invalid service address")

        grouped[groomer_id].append(
            Appointment(
                start=_aware(row.get("start")),
                end=_aware(row.get("end")),
                address=service_address.strip(),
                appointment_id=appointment_id,
            )
        )

    return Snapshot(
        sync_verified=True,
        complete_all_calendars=True,
        groomer_ids=ids,
        appointments_by_groomer={
            groomer: tuple(appointments)
            for groomer, appointments in grouped.items()
        },
    )
'@ | Set-Content -LiteralPath .\pavi_step3_snapshot_adapter.py -Encoding UTF8