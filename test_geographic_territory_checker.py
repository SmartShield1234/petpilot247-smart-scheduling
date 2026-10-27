
import json
import unittest
from pathlib import Path

from geographic_territory_checker import (
    normalize_zip,
    check_territory,
)


class TestGeographicTerritoryChecker(unittest.TestCase):

    def test_valid_zip(self):
        self.assertEqual(normalize_zip("19006"), "19006")

    def test_invalid_zip(self):
        self.assertIsNone(normalize_zip("1234"))
        self.assertIsNone(normalize_zip("ABCDE"))
        self.assertIsNone(normalize_zip(None))

    def test_unverified_territory_rejected(self):
        territory = {
            "type": "zip_codes",
            "zip_codes": ["19006"],
            "verified": False,
        }
        self.assertFalse(check_territory("19006", territory))

    def test_verified_simulation_fixture(self):
        territory = {
            "type": "zip_codes",
            "zip_codes": ["19006"],
            "verified": True,
        }
        self.assertTrue(check_territory("19006", territory))
        self.assertFalse(check_territory("99999", territory))

    def test_invalid_territory_rejected(self):
        self.assertFalse(check_territory("19006", None))
        self.assertFalse(check_territory("19006", {}))

    def test_all_inventory_assignments_unverified(self):
        source = json.loads(
            Path("geographic_eligibility_source.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(len(source["groomers"]), 15)
        self.assertFalse(source["live_scheduling_authorized"])

        for record in source["groomers"]:
            self.assertFalse(
                record["approved_for_mobile_grooming"]
            )
            self.assertFalse(
                record["geographic_eligibility_verified"]
            )
            self.assertFalse(
                check_territory(
                    "19006",
                    record["service_territory"],
                )
            )


if __name__ == "__main__":
    unittest.main()
