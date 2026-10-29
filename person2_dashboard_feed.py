
"""Person 2: read-only, fail-closed dashboard feed builder.

This module formats independently verified appointment, groomer,
territory, and location evidence for the PetPilot247 dashboard.

It does not authenticate HTTP requests, fetch live appointments,
geocode addresses, or authorize booking.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from person2_live_map_adapter import (
    MapEvidenceUnavailable,
    build_authorized_map_record,
)


class DashboardFeedUnavailable(ValueError):
    """The dashboard feed cannot safely be produced."""


def build_dashboard_feed(
    *,
    evidence_records: Iterable[Mapping[str, Any]],
    source_authenticated: bool = False,
    viewer_authorized: bool = False,
) -> dict[str, Any]:
    """Build a feed using evidence supplied by trusted backend authorities.

    source_authenticated and viewer_authorized must be established
    independently by the trusted server, not by browser input.
    """

    if source_authenticated is not True:
        raise DashboardFeedUnavailable(
            "Authenticated appointment source is required"
        )

    if viewer_authorized is not True:
        raise DashboardFeedUnavailable(
            "Authorized dashboard viewer is required"
        )

    if isinstance(evidence_records, (str, bytes, Mapping)):
        raise DashboardFeedUnavailable(
            "Evidence records must be an iterable of records"
        )

    try:
        iterator = iter(evidence_records)
    except TypeError as exc:
        raise DashboardFeedUnavailable(
            "Evidence records are unavailable"
        ) from exc

    appointments = []
    seen_ids = set()

    try:
        for index, evidence in enumerate(iterator):
            if not isinstance(evidence, Mapping):
                raise DashboardFeedUnavailable(
                    f"Record {index} is not a valid evidence mapping"
                )

            required_parts = (
                "appointment",
                "groomer",
                "territory",
                "location",
            )

            for part in required_parts:
                if not isinstance(evidence.get(part), Mapping):
                    raise DashboardFeedUnavailable(
                        f"Record {index} is missing {part} evidence"
                    )

            record = build_authorized_map_record(
                appointment=evidence["appointment"],
                groomer=evidence["groomer"],
                territory=evidence["territory"],
                location=evidence["location"],
            )

            if record["id"] in seen_ids:
                raise DashboardFeedUnavailable(
                    "Duplicate appointment ID detected"
                )

            seen_ids.add(record["id"])
            appointments.append(record)

    except MapEvidenceUnavailable as exc:
        raise DashboardFeedUnavailable(
            f"Appointment evidence rejected: {exc}"
        ) from exc

    return {
        "status": "OK",
        "source_authenticated": True,
        "records_authorized": True,
        "appointments": appointments,
    }
