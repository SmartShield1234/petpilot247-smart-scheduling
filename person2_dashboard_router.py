
"""Person 2: authenticated, read-only appointment dashboard API.

Security:
- No viewer authentication configured by default.
- No appointment evidence provider configured by default.
- Both authorities must be installed by trusted server startup code.
- Never accept authorization or verification flags from browser input.
- Never authorize or modify bookings.
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


# Trusted server-side callback contracts.
ViewerAuthority = Callable[[Request], bool]

EvidenceProvider = Callable[
    [],
    Iterable[Mapping[str, Any]],
]


# Fail closed until trusted providers are installed.
_viewer_authority: ViewerAuthority | None = None
_evidence_provider: EvidenceProvider | None = None


def configure_dashboard_authorities(
    *,
    viewer_authority: ViewerAuthority | None,
    evidence_provider: EvidenceProvider | None,
) -> None:
    """Install trusted authorities from application startup only.

    viewer_authority must independently authenticate the session
    and authorize the current staff member to view the dashboard.

    evidence_provider must obtain independently verified
    appointment, groomer, territory, and location evidence.

    Do not configure these using browser-supplied flags or data.
    """
    global _viewer_authority, _evidence_provider

    _viewer_authority = viewer_authority
    _evidence_provider = evidence_provider


@router.get("/dashboard/appointments")
def dashboard_appointments(request: Request):
    """Return authorized appointment locations without booking writes."""

    # Step 1: Require a trusted viewer authorization callback.
    if _viewer_authority is None:
        raise HTTPException(
            status_code=503,
            detail="Dashboard authorization unavailable",
        )

    # Step 2: Authenticate and authorize the viewer.
    try:
        authorized = _viewer_authority(request)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Dashboard authorization unavailable",
        ) from exc

    if authorized is not True:
        raise HTTPException(
            status_code=403,
            detail="Forbidden",
        )

    # Step 3: Require a verified backend evidence provider.
    if _evidence_provider is None:
        raise HTTPException(
            status_code=503,
            detail="Verified appointment feed unavailable",
        )

    # Step 4: Build the read-only feed from trusted evidence.
    try:
        evidence = _evidence_provider()

        feed = build_dashboard_feed(
            evidence_records=evidence,
            source_authenticated=True,
            viewer_authorized=True,
        )

        return feed

    except DashboardFeedUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Verified appointment feed unavailable",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Verified appointment feed unavailable",
        ) from exc
