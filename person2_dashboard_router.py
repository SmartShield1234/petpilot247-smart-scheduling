
"""Person 2: authenticated, scoped, read-only dashboard API.

Trusted server startup must install independently verified authorities.
No live provider is configured by default. No booking writes.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from person2_dashboard_feed import (
    DashboardFeedUnavailable,
    build_dashboard_feed,
)

router = APIRouter(
    prefix="/api/v1/person2",
    tags=["Person 2 Dashboard"],
)

# Callback contracts:
# viewer_authority(request) -> verified viewer identity and scope
# evidence_provider(viewer) -> evidence records within that scope
#
# Neither callback may trust browser-supplied identity or permissions.

ViewerAuthority = Callable[[Request], Mapping[str, Any]]
EvidenceProvider = Callable[
    [Mapping[str, Any]],
    Iterable[Mapping[str, Any]],
]

_viewer_authority: ViewerAuthority | None = None
_evidence_provider: EvidenceProvider | None = None


def configure_dashboard_authorities(
    *,
    viewer_authority: ViewerAuthority | None,
    evidence_provider: EvidenceProvider | None,
) -> None:
    """Install trusted, server-controlled authorities.

    viewer_authority must independently authenticate the request
    and return the verified staff identity and permitted scope.

    evidence_provider must enforce that scope at the data source,
    returning only independently verified appointment evidence.

    No browser-supplied identity, scope, or verification flags.
    """
    global _viewer_authority, _evidence_provider

    _viewer_authority = viewer_authority
    _evidence_provider = evidence_provider


def _validate_viewer(viewer: Any) -> Mapping[str, Any]:
    """Require an authenticated viewer with an explicit scope."""

    if not isinstance(viewer, Mapping):
        raise ValueError("Verified viewer identity required")

    staff_id = viewer.get("staff_id")
    location_id = viewer.get("location_id")
    allowed_calendar_ids = viewer.get("allowed_calendar_ids")

    if not isinstance(staff_id, str) or not staff_id.strip():
        raise ValueError("Verified staff identity required")

    if not isinstance(location_id, str) or not location_id.strip():
        raise ValueError("Verified location scope required")

    if not isinstance(allowed_calendar_ids, (list, tuple, frozenset)):
        raise ValueError("Verified calendar scope required")

    if not allowed_calendar_ids or any(
        not isinstance(item, str) or not item.strip()
        for item in allowed_calendar_ids
    ):
        raise ValueError("Invalid calendar scope")

    if len(set(allowed_calendar_ids)) != len(allowed_calendar_ids):
        raise ValueError("Duplicate calendar scope")

    if viewer.get("authenticated") is not True:
        raise ValueError("Viewer authentication not verified")

    return {
        "staff_id": staff_id.strip(),
        "location_id": location_id.strip(),
        "allowed_calendar_ids": frozenset(allowed_calendar_ids),
        "authenticated": True,
    }


@router.get("/dashboard/appointments")
def dashboard_appointments(request: Request):
    """Return only independently authorized appointment locations."""

    if _viewer_authority is None:
        raise HTTPException(
            status_code=503,
            detail="Dashboard authorization unavailable",
        )

    try:
        viewer = _validate_viewer(_viewer_authority(request))
    except Exception as exc:
        raise HTTPException(
            status_code=403,
            detail="Forbidden",
        ) from exc

    if _evidence_provider is None:
        raise HTTPException(
            status_code=503,
            detail="Verified appointment feed unavailable",
        )

    try:
        evidence = _evidence_provider(viewer)

        # Independently enforce the viewer's calendar scope.
        # The provider must also enforce location and tenant
        # boundaries at the trusted backend data source.
        scoped_records = []

        for record in evidence:
            if not isinstance(record, Mapping):
                raise DashboardFeedUnavailable(
                    "Invalid appointment evidence"
                )

            appointment = record.get("appointment")
            if not isinstance(appointment, Mapping):
                raise DashboardFeedUnavailable(
                    "Missing appointment evidence"
                )

            if appointment.get("calendar_id") not in viewer[
                "allowed_calendar_ids"
            ]:
                raise DashboardFeedUnavailable(
                    "Appointment outside authorized calendar scope"
                )

            if appointment.get("location_id") != viewer["location_id"]:
                raise DashboardFeedUnavailable(
                    "Appointment outside authorized location scope"
                )

            scoped_records.append(record)

        return build_dashboard_feed(
            evidence_records=scoped_records,
            source_authenticated=True,
            viewer_authorized=True,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Verified appointment feed unavailable",
        ) from exc
