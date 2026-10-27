
import unittest
from datetime import datetime, timedelta, timezone

from geographic_eligibility_decisions import decide_eligibility


class TestGeographicEligibilityDecisions(unittest.TestCase):

    def make_record(self, verified_at=None):
        if verified_at is None:
            verified_at = datetime.now(timezone.utc)

        return {
            "approved_for_mobile_grooming": True,
            "geographic_eligibility_verified": True,
            "service_territory": {
                "type": "zip_codes",
                "zip_codes": ["19006", "19002"],
                "verified": True,
            },
            "verification": {
                "source": "FICTIONAL_TEST_AUTHORITY",
                "reviewed_by": "TEST_ONLY",
                "verified_at": verified_at.isoformat(),
            },
        }

    def test_eligible_simulation(self):
        result = decide_eligibility(
            "19006",
            self.make_record(),
            trusted_source=True,
        )
        self.assertEqual(result["decision"], "eligible")
        self.assertTrue(result["eligible"])

    def test_outside_territory(self):
        result = decide_eligibility(
            "99999",
            self.make_record(),
            trusted_source=True,
        )
        self.assertEqual(result["decision"], "ineligible")

    def test_expired_evidence(self):
        record = self.make_record(
            datetime.now(timezone.utc) - timedelta(hours=25)
        )
        result = decide_eligibility(
            "19006", record, trusted_source=True
        )
        self.assertEqual(result["decision"], "unavailable")

    def test_future_evidence(self):
        record = self.make_record(
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        result = decide_eligibility(
            "19006", record, trusted_source=True
        )
        self.assertEqual(result["decision"], "unavailable")

    def test_untrusted_evidence(self):
        result = decide_eligibility(
            "19006",
            self.make_record(),
        )
        self.assertEqual(result["decision"], "unavailable")

    def test_missing_verification(self):
        record = self.make_record()
        record["verification"]["reviewed_by"] = None

        result = decide_eligibility(
            "19006", record, trusted_source=True
        )
        self.assertEqual(result["decision"], "unavailable")

    def test_invalid_customer_zip(self):
        result = decide_eligibility(
            "invalid",
            self.make_record(),
            trusted_source=True,
        )
        self.assertEqual(result["decision"], "unavailable")

    def test_unapproved_groomer(self):
        record = self.make_record()
        record["approved_for_mobile_grooming"] = False

        result = decide_eligibility(
            "19006", record, trusted_source=True
        )
        self.assertEqual(result["decision"], "ineligible")


if __name__ == "__main__":
    unittest.main()

