
"""PetPilot247 authenticated geographic data-provider contract.

Defines the evidence required before staff availability or geographic
eligibility can be trusted.

This module does not call GHL, authenticate API responses, approve
groomers, or authorize live booking.

Production integrations must use a server-controlled authenticated
source and independently verify identity, schedule, territory, and
evidence freshness.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


EvidenceStatus = Literal[
    "verified",
    "unverified",
    "expired",
    "unavailable",
]


@dataclass(frozen=True)
class AuthenticatedStaffEvidence:
    calendar_id: str
    groomer_id: str
    appointment_date: date
    timezone_name: str

    source_system: str
    source_record_id: str | None

    identity_mapping_verified: bool
    working_hours_verified: bool
    schedule_exceptions_verified: bool
    territory_verified: bool

    verified_at_utc: datetime | None
    evidence_expires_at_utc: datetime | None

    evidence_status: EvidenceStatus

    # These fields are intentionally conservative.
    # Booking authorization belongs to Pavi's scheduling system.
    live_booking_authorized: bool = False


@dataclass(frozen=True)
class EvidenceDecision:
    decision: Literal["verified", "unavailable"]
    reason: str


def unavailable(reason: str) -> EvidenceDecision:
    return EvidenceDecision(
        decision="unavailable",
        reason=reason,
    )


def validate_authenticated_evidence(
    evidence: AuthenticatedStaffEvidence | None,
    *,
    calendar_id: str,
    groomer_id: str,
    appointment_date: date,
    timezone_name: str,
    authenticated_source: bool = False,
    now_utc: datetime | None = None,
) -> EvidenceDecision:
    """Validate an evidence envelope without authorizing booking.

    authenticated_source must be supplied only by trusted server-side
    integration code, never from a request body or query parameter.

    A verified envelope is necessary but not sufficient for scheduling.
    Actual working hours, time-off, appointment conflicts, geographic
    coverage, and source provenance must be checked separately.
    """

    if authenticated_source is not True:
        return unavailable(
            "Authenticated source not established"
        )

    if not isinstance(
        evidence,
        AuthenticatedStaffEvidence,
    ):
        return unavailable(
            "Missing authenticated staff evidence"
        )

    if (
        not isinstance(calendar_id, str)
        or not calendar_id.strip()
        or not isinstance(groomer_id, str)
        or not groomer_id.strip()
        or type(appointment_date) is not date
        or not isinstance(timezone_name, str)
        or not timezone_name.strip()
    ):
        return unavailable(
            "Invalid requested staff identity or date"
        )

    if (
        evidence.calendar_id != calendar_id
        or evidence.groomer_id != groomer_id
    ):
        return unavailable(
            "Calendar-to-groomer identity mismatch"
        )

    if (
        evidence.appointment_date != appointment_date
        or evidence.timezone_name != timezone_name
    ):
        return unavailable(
            "Appointment date or timezone mismatch"
        )

    try:
        ZoneInfo(timezone_name)
    except (
        ZoneInfoNotFoundError,
        ValueError,
        TypeError,
    ):
        return unavailable(
            "Invalid appointment timezone"
        )

    if (
        not isinstance(evidence.source_system, str)
        or not evidence.source_system.strip()
        or not isinstance(evidence.source_record_id, str)
        or not evidence.source_record_id.strip()
    ):
        return unavailable(
            "Missing source provenance"
        )

    if evidence.evidence_status != "verified":
        return unavailable(
            "Evidence is not verified"
        )

    checks = {
        "identity mapping": evidence.identity_mapping_verified,
        "working hours": evidence.working_hours_verified,
        "schedule exceptions": evidence.schedule_exceptions_verified,
        "territory": evidence.territory_verified,
    }

    for name, value in checks.items():
        if value is not True:
            return unavailable(
                f"Unverified {name}"
            )

    if evidence.live_booking_authorized is not False:
        return unavailable(
            "Unexpected booking authorization flag"
        )

    verified_at = evidence.verified_at_utc
    expires_at = evidence.evidence_expires_at_utc

    if (
        not isinstance(verified_at, datetime)
        or not isinstance(expires_at, datetime)
        or verified_at.tzinfo is None
        or expires_at.tzinfo is None
        or verified_at.utcoffset() is None
        or expires_at.utcoffset() is None
    ):
        return unavailable(
            "Missing timezone-aware evidence timestamps"
        )

    if (
        verified_at.utcoffset().total_seconds() != 0
        or expires_at.utcoffset().total_seconds() != 0
    ):
        return unavailable(
            "Evidence timestamps must be UTC"
        )

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    if (
        not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        return unavailable(
            "Invalid current verification time"
        )

    now_utc = now_utc.astimezone(timezone.utc)
    verified_at = verified_at.astimezone(timezone.utc)
    expires_at = expires_at.astimezone(timezone.utc)

    if verified_at > now_utc:
        return unavailable(
            "Future-dated verification"
        )

    if expires_at <= verified_at:
        return unavailable(
            "Invalid evidence expiration"
        )

    if now_utc >= expires_at:
        return unavailable(
            "Expired evidence"
        )

    # An expiration timestamp is not itself an approved freshness
    # policy. The authenticated provider must enforce the agreed
    # maximum evidence age before invoking this validator.

    return EvidenceDecision(
        decision="verified",
        reason=(
            "Evidence envelope validated; "
            "operational eligibility still requires verification"
        ),
    )
