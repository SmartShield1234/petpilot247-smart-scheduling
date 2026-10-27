
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from geographic_evidence_validator import validate_geographic_evidence


class TestGeographicEvidenceValidator(unittest.TestCase):

    def setUp(self):
        self.calendar_id = "TEST_CALENDAR"
        self.groomer_id = "TEST_GROOMER"

        self.record = {
            "calendar_id": self.calendar_id,
            "ghl_user_id": self.groomer_id,
            "approved_for_mobile_grooming": True,
            "geographic_eligibility_verified": True,
            "service_territory": {
                "type": "zip_codes",
                "zip_codes": ["19006"],
                "verified": True,
            },
            "depot_address": "123 Fictional Depot Road, PA 19006",
            "working_schedule": {
                "timezone": "America/New_York",
                "days": ["Monday", "Tuesday"],
                "start_time": "09:00",
                "end_time": "17:00",
                "verified": True,
            },
            "scheduling_buffers": {
                "setup_minutes": 10,
                "cleanup_minutes": 10,
                "buffer_minutes": 15,
                "verified": True,
            },
            "verification": {
                "source": "FICTIONAL_TEST_AUTHORITY",
                "reviewed_by": "TEST_ONLY",
                "verified_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        }

    def check(self, record):
        return validate_geographic_evidence(
            record,
            self.calendar_id,
            self.groomer_id,
        )

    def test_complete_fictional_record(self):
        result = self.check(self.record)
        self.assertTrue(result["valid"])

    def test_wrong_groomer(self):
        record = copy.deepcopy(self.record)
        record["ghl_user_id"] = "WRONG_GROOMER"
        self.assertFalse(self.check(record)["valid"])

    def test_wrong_calendar(self):
        record = copy.deepcopy(self.record)
        record["calendar_id"] = "WRONG_CALENDAR"
        self.assertFalse(self.check(record)["valid"])

    def test_expired_evidence(self):
        record = copy.deepcopy(self.record)
        record["verification"]["verified_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        self.assertFalse(self.check(record)["valid"])

    def test_missing_depot(self):
        record = copy.deepcopy(self.record)
        record["depot_address"] = None
        self.assertFalse(self.check(record)["valid"])

    def test_unverified_schedule(self):
        record = copy.deepcopy(self.record)
        record["working_schedule"]["verified"] = False
        self.assertFalse(self.check(record)["valid"])

    def test_missing_buffers(self):
        record = copy.deepcopy(self.record)
        record["scheduling_buffers"]["buffer_minutes"] = None
        self.assertFalse(self.check(record)["valid"])

    def test_unverified_territory(self):
        record = copy.deepcopy(self.record)
        record["service_territory"]["verified"] = False
        self.assertFalse(self.check(record)["valid"])

    def test_actual_records_blocked(self):
        with open(
            "geographic_eligibility_source.json",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        self.assertFalse(data["live_scheduling_authorized"])
        self.assertEqual(data["source_status"], "unverified")
        self.assertEqual(len(data["groomers"]), 15)

        for record in data["groomers"]:
            result = validate_geographic_evidence(
                record,
                record["calendar_id"],
                record["ghl_user_id"],
            )
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
