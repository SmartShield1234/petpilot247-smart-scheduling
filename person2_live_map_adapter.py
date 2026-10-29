
"""Person 2: read-only, fail-closed appointment-to-map adapter.

All inputs must come from trusted, authenticated backend authorities.
This module does not fetch GHL data, geocode addresses, or authorize booking.
"""

from datetime import datetime, timezone
from typing import Any, Mapping


class MapEvidenceUnavailable(ValueError):
    """Required evidence is missing, inconsistent, or unverified."""


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MapEvidenceUnavailable(f"{field} is required")
    return value.strip()


def _require_verified(value: Any, field: str) -> None:
    if value is not True:
        raise MapEvidenceUnavailable(f"{field} is not verified")


def _require_fresh_timestamp(value: Any, field: str) -> None:
    raw = _require_text(value, field)

    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MapEvidenceUnavailable(
            f"{field} is invalid"
        ) from exc

    if timestamp.tzinfo is None:
        raise MapEvidenceUnavailable(
            f"{field} must include a timezone"
        )

    if timestamp.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise MapEvidenceUnavailable(
            f"{field} has expired"
        )


def build_authorized_map_record(
    *,
    appointment: Mapping[str, Any],
    groomer: Mapping[str, Any],
    territory: Mapping[str, Any],
    location: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one read-only map record from independently verified evidence."""

    # Appointment evidence must be authenticated and revision-confirmed.
    _require_verified(
        appointment.get("source_authenticated"),
        "appointment.source_authenticated",
    )
    _require_verified(
        appointment.get("revision_verified"),
        "appointment.revision_verified",
    )
    _require_verified(
        appointment.get("service_address_verified"),
        "appointment.service_address_verified",
    )

    appointment_id = _require_text(
        appointment.get("appointment_id"), "appointment.appointment_id"
    )
    calendar_id = _require_text(
        appointment.get("calendar_id"), "appointment.calendar_id"
    )
    groomer_id = _require_text(
        appointment.get("groomer_id"), "appointment.groomer_id"
    )
    address = _require_text(
        appointment.get("service_address"), "appointment.service_address"
    )

    # Groomer identity and approval must match the appointment.
    _require_verified(
        groomer.get("source_authenticated"),
        "groomer.source_authenticated",
    )
    _require_verified(
        groomer.get("identity_mapping_verified"),
        "groomer.identity_mapping_verified",
    )
    _require_verified(
        groomer.get("production_approved"),
        "groomer.production_approved",
    )

    if groomer.get("groomer_id") != groomer_id:
        raise MapEvidenceUnavailable("Groomer identity mismatch")

    if groomer.get("calendar_id") != calendar_id:
        raise MapEvidenceUnavailable("Groomer calendar mismatch")

    # Territory must be approved for this groomer and service address.
    _require_verified(
        territory.get("source_authenticated"),
        "territory.source_authenticated",
    )
    _require_verified(
        territory.get("verified"),
        "territory.verified",
    )
    _require_verified(
        territory.get("address_eligible"),
        "territory.address_eligible",
    )

    if territory.get("groomer_id") != groomer_id:
        raise MapEvidenceUnavailable("Territory groomer mismatch")

    if territory.get("service_address") != address:
        raise MapEvidenceUnavailable("Territory address mismatch")

    # Coordinates must be tied to the verified appointment service address.
    _require_verified(
        location.get("source_authenticated"),
        "location.source_authenticated",
    )
    _require_verified(
        location.get("geocoding_verified"),
        "location.geocoding_verified",
    )

    if location.get("appointment_id") != appointment_id:
        raise MapEvidenceUnavailable("Location appointment mismatch")

    if location.get("service_address") != address:
        raise MapEvidenceUnavailable("Location address mismatch")

    lat = location.get("lat")
    lng = location.get("lng")

    if (
        isinstance(lat, bool)
        or isinstance(lng, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
        or not (-90 <= lat <= 90)
        or not (-180 <= lng <= 180)
    ):
        raise MapEvidenceUnavailable("Invalid verified coordinates")

    # A trusted backend must also supply an unexpired authorization.
    _require_fresh_timestamp(
        appointment.get("evidence_expires_at_utc"),
        "appointment.evidence_expires_at_utc",
    )

    status = _require_text(
        appointment.get("status"), "appointment.status"
    )
    if status not in {"Scheduled", "Confirmed"}:
        raise MapEvidenceUnavailable("Appointment status is not displayable")

    return {
        "id": appointment_id,
        "stop": _require_text(
            appointment.get("customer_label"),
            "appointment.customer_label",
        ),
        "service": _require_text(
            appointment.get("service"),
            "appointment.service",
        ),
        "technician": _require_text(
            groomer.get("display_name"),
            "groomer.display_name",
        ),
        "time": _require_text(
            appointment.get("display_time"),
            "appointment.display_time",
        ),
        "status": status,
        "lat": float(lat),
        "lng": float(lng),
    }
