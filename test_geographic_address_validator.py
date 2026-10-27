
import unittest
from copy import deepcopy

from geographic_address_validator import validate_confirmed_address


class TestGeographicAddressValidator(unittest.TestCase):

    def setUp(self):
        self.address = "123 Test Street, Philadelphia, PA 19103"
        self.evidence = {
            "requested_address": self.address,
            "verified": True,
            "country_code": "US",
            "address_complete": True,
            "location_type": "ROOFTOP",
            "postal_code": "19103",
            "formatted_address": self.address,
        }

    def check(self, evidence):
        return validate_confirmed_address(
            self.address,
            evidence,
        )

    def test_valid_fictional_address(self):
        result = self.check(self.evidence)
        self.assertTrue(result["valid"])
        self.assertEqual(result["customer_zip"], "19103")

    def test_unverified_address(self):
        evidence = deepcopy(self.evidence)
        evidence["verified"] = False
        self.assertFalse(self.check(evidence)["valid"])

    def test_wrong_address(self):
        evidence = deepcopy(self.evidence)
        evidence["requested_address"] = "999 Other Street"
        self.assertFalse(self.check(evidence)["valid"])

    def test_missing_zip(self):
        evidence = deepcopy(self.evidence)
        evidence["postal_code"] = None
        self.assertFalse(self.check(evidence)["valid"])

    def test_invalid_zip(self):
        evidence = deepcopy(self.evidence)
        evidence["postal_code"] = "INVALID"
        self.assertFalse(self.check(evidence)["valid"])

    def test_non_us_address(self):
        evidence = deepcopy(self.evidence)
        evidence["country_code"] = "CA"
        self.assertFalse(self.check(evidence)["valid"])

    def test_incomplete_address(self):
        evidence = deepcopy(self.evidence)
        evidence["address_complete"] = False
        self.assertFalse(self.check(evidence)["valid"])

    def test_non_rooftop_location(self):
        evidence = deepcopy(self.evidence)
        evidence["location_type"] = "APPROXIMATE"
        self.assertFalse(self.check(evidence)["valid"])

    def test_missing_evidence(self):
        self.assertFalse(self.check(None)["valid"])


if __name__ == "__main__":
    unittest.main()

