
import os

from fastapi.testclient import TestClient
import main


DEV_HEADERS = {
    "x-petpilot-dev-token": os.environ["PETPILOT_DEV_API_TOKEN"]
}

client = TestClient(main.app)

original_enabled = main.GOOGLE_MAPS_API_ENABLED
original_key = main.GOOGLE_MAPS_API_KEY

payload = {
    "requested_start": "2026-10-12T09:00:00-04:00",
    "service_minutes": 60,
}

try:
    print("===== PERSON 1 - STEP 8.6 =====")

    # Test 1: Missing Google Maps API key
    main.GOOGLE_MAPS_API_ENABLED = True
    main.GOOGLE_MAPS_API_KEY = None

    response = client.post(
        "/recommend-groomers",
        json=payload,
        headers=DEV_HEADERS,
    )

    assert response.status_code == 503, response.text
    print("Missing Google API key | PASS")

    # Test 2: Unverified appointment synchronization
    main.GOOGLE_MAPS_API_KEY = "test-key-not-real"

    response = client.post(
        "/recommend-groomers",
        json=payload,
        headers=DEV_HEADERS,
    )

    assert response.status_code == 503, response.text

    detail = str(response.json().get("detail", "")).lower()

    assert "synchronization is not verified" in detail, detail

    print("Unverified synchronization blocks recommendations | PASS")

    # Test 3: Missing verified depot and address evidence
    payload["customer_address"] = "Philadelphia, PA"

    response = client.post(
        "/recommend-groomers",
        json=payload,
        headers=DEV_HEADERS,
    )

    assert response.status_code == 503, response.text

    print("Unsafe recommendation request rejected | PASS")

    print("PASS: Live Google Routes safety checks completed.")

finally:
    main.GOOGLE_MAPS_API_ENABLED = original_enabled
    main.GOOGLE_MAPS_API_KEY = original_key
