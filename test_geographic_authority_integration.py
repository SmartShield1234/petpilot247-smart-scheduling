
import os
import unittest
from datetime import date
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from geographic_eligibility_router import (
    router,
    EligibilityResponse,
    configure_geographic_authority,
)


class TestGeographicAuthorityIntegration(unittest.TestCase):

    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

        self.key_patch = patch.dict(
            os.environ,
            {"PETPILOT_GEO_ELIGIBILITY_API_KEY": "test-only-secret"},
        )
        self.key_patch.start()

        self.payload = {
            "calendar_id": "TEST_CALENDAR",
            "groomer_id": "TEST_GROOMER",
            "customer_address": "123 Test Street, PA 19006",
            "appointment_date": "2026-10-26",
            "timezone_name": "America/New_York",
        }

        self.headers = {
            "X-Geo-Eligibility-Key": "test-only-secret",
        }

        configure_geographic_authority(None)

    def tearDown(self):
        configure_geographic_authority(None)
        self.key_patch.stop()
        self.client.close()

    def verify(self):
        return self.client.post(
            "/api/v1/geographic-eligibility/verify",
            json=self.payload,
            headers=self.headers,
        )

    def make_response(self, decision, eligible, verified):
        return EligibilityResponse(
            decision=decision,
            calendar_id="TEST_CALENDAR",
            groomer_id="TEST_GROOMER",
            eligible=eligible,
            evidence_verified=verified,
            reason="Fictional test authority",
        )

    def test_no_authority(self):
        response = self.verify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"], "unavailable")

    def test_eligible_response(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            return self.make_response("eligible", True, True)

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "eligible")

    def test_ineligible_response(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            return self.make_response("ineligible", False, True)

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "ineligible")

    def test_unavailable_response(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            return self.make_response("unavailable", False, False)

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_identity_mismatch_rejected(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            return EligibilityResponse(
                decision="eligible",
                calendar_id="WRONG_CALENDAR",
                groomer_id=groomer_id,
                eligible=True,
                evidence_verified=True,
                reason="Fictional test",
            )

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_contradictory_evidence_rejected(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            return self.make_response("eligible", True, False)

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_authority_failure(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            raise RuntimeError("Simulated authority failure")

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_missing_appointment_date_fails_closed(self):
        self.payload.pop("appointment_date")
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_missing_timezone_fails_closed(self):
        self.payload.pop("timezone_name")
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_invalid_timezone_fails_closed(self):
        self.payload["timezone_name"] = "Invalid/Timezone"
        self.assertEqual(self.verify().json()["decision"], "unavailable")

    def test_five_argument_authority(self):
        async def authority(calendar_id, groomer_id, address, appointment_date, timezone_name):
            self.assertEqual(appointment_date, date(2026, 10, 26))
            self.assertEqual(timezone_name, "America/New_York")
            self.assertEqual(calendar_id, "TEST_CALENDAR")
            self.assertEqual(groomer_id, "TEST_GROOMER")
            return self.make_response("eligible", True, True)

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "eligible")

    def test_missing_api_key_rejected(self):
        self.headers = {}
        self.assertEqual(self.verify().status_code, 401)

    def test_wrong_api_key_rejected(self):
        self.headers["X-Geo-Eligibility-Key"] = "wrong-key"
        self.assertEqual(self.verify().status_code, 401)

    def test_legacy_three_argument_authority_fails_closed(self):
        async def authority(calendar_id, groomer_id, address):
            return self.make_response("eligible", True, True)

        configure_geographic_authority(authority)
        self.assertEqual(self.verify().json()["decision"], "unavailable")


if __name__ == "__main__":
    unittest.main()
