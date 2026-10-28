
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from geographic_eligibility_router import router


class TestGeographicEligibilityRouter(unittest.TestCase):

    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

        self.endpoint = "/api/v1/geographic-eligibility/verify"

        self.payload = {
            "calendar_id": "test-calendar",
            "groomer_id": "test-groomer",
            "customer_address": "123 Test Street, Philadelphia, PA 19103",
        }

    def test_missing_authentication(self):
        with patch.dict(
            os.environ,
            {"PETPILOT_GEO_ELIGIBILITY_API_KEY": "test-only-token"},
        ):
            response = self.client.post(
                self.endpoint,
                json=self.payload,
            )

        self.assertEqual(response.status_code, 401)

    def test_invalid_authentication(self):
        with patch.dict(
            os.environ,
            {"PETPILOT_GEO_ELIGIBILITY_API_KEY": "test-only-token"},
        ):
            response = self.client.post(
                self.endpoint,
                json=self.payload,
                headers={"X-Geo-Eligibility-Key": "wrong-token"},
            )

        self.assertEqual(response.status_code, 401)

    def test_missing_server_key(self):
        with patch.dict(
            os.environ,
            {"PETPILOT_GEO_ELIGIBILITY_API_KEY": ""},
        ):
            response = self.client.post(
                self.endpoint,
                json=self.payload,
                headers={"X-Geo-Eligibility-Key": "test-only-token"},
            )

        self.assertEqual(response.status_code, 401)

    def test_unverified_authority(self):
        with patch.dict(
            os.environ,
            {"PETPILOT_GEO_ELIGIBILITY_API_KEY": "test-only-token"},
        ):
            response = self.client.post(
                self.endpoint,
                json=self.payload,
                headers={"X-Geo-Eligibility-Key": "test-only-token"},
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["decision"], "unavailable")
        self.assertFalse(result["eligible"])
        self.assertFalse(result["evidence_verified"])

    def test_invalid_request(self):
        with patch.dict(
            os.environ,
            {"PETPILOT_GEO_ELIGIBILITY_API_KEY": "test-only-token"},
        ):
            response = self.client.post(
                self.endpoint,
                json={
                    "calendar_id": "",
                    "groomer_id": "",
                    "customer_address": "",
                },
                headers={"X-Geo-Eligibility-Key": "test-only-token"},
            )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
