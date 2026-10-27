
import unittest
from datetime import datetime, timezone

from pavi_slot_validator import Appointment, Candidate, evaluate


def at(hour, minute=0):
    return datetime(2026, 10, 28, hour, minute, tzinfo=timezone.utc)


def make_candidate(**overrides):
    values = dict(
        groomer_id="test-groomer",
        start=at(10, 30),
        work_start=at(9),
        work_end=at(17),
        free_starts=frozenset({at(10, 30)}),
        appointments=(
            Appointment(at(9), at(10), "Previous Customer", "appt-1"),
            Appointment(at(12, 30), at(13, 30), "Next Customer", "appt-2"),
        ),
        service_minutes=60,
        setup_minutes=5,
        cleanup_minutes=10,
        buffer_minutes=10,
        previous_drive_minutes=20,
        next_drive_minutes=15,
        direct_drive_minutes=25,
        preferred_start=at(10, 30),
        evidence_verified=True,
    )
    values.update(overrides)
    return Candidate(**values)


class TestPerson2Scheduling(unittest.TestCase):

    def test_insufficient_travel_time_rejected(self):
        candidate = make_candidate(
            start=at(10, 15),
            free_starts=frozenset({at(10, 15)}),
            preferred_start=at(10, 15),
        )
        self.assertIsNone(evaluate(candidate))

    def test_valid_appointment_accepted(self):
        result = evaluate(make_candidate())
        self.assertIsNotNone(result)
        self.assertFalse(result["booking_authorized"])

    def test_overlapping_appointment_rejected(self):
        candidate = make_candidate(
            appointments=(
                Appointment(at(10), at(11), "Existing Customer", "existing-appt"),
            )
        )
        self.assertIsNone(evaluate(candidate))

    def test_unverified_evidence_rejected(self):
        candidate = make_candidate(evidence_verified=False)
        self.assertIsNone(evaluate(candidate))


if __name__ == "__main__":
    unittest.main()
