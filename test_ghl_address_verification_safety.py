
import asyncio
import os
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

import main
from maps_service import MapsServiceError


async def run_test():
    if os.getenv("PETPILOT_ENV") != "development":
        raise RuntimeError("Development mode required")

    if os.getenv(
        "PETPILOT_LIVE_BOOKING_ENABLED", ""
    ).lower() != "false":
        raise RuntimeError("Live booking must remain disabled")

    if os.getenv(
        "GOOGLE_MAPS_API_ENABLED", ""
    ).lower() != "false":
        raise RuntimeError("Google Maps endpoint mode must remain disabled")

    calls = 0

    async def fake_contact_lookup(contact_id):
        nonlocal calls
        calls += 1

        return {
            "contact": {
                "address1": "Philadelphia City Hall",
                "city": "Philadelphia",
                "state": "PA",
                "postalCode": "19107",
                "country": "US",
            }
        }

    appointments = [
        {
            "groomer_id": "silpa",
            "contact_id": "fictional-contact-1",
            "customer_address": None,
        },
        {
            "groomer_id": "silpa",
            "contact_id": "fictional-contact-1",
            "customer_address": None,
        },
        {
            "groomer_id": "john",
            "contact_id": None,
            "customer_address": None,
        },
        {
            "groomer_id": "ambily",
            "contact_id": "fictional-contact-2",
            "customer_address": "Liberty Bell, Philadelphia, PA",
            "address_source": "service_confirmed",
        },
    ]

    with patch.object(main, "get_ghl_contact", fake_contact_lookup):
        enriched = await main.enrich_appointment_addresses(appointments)

    assert enriched[0]["address_source"] == "contact_unverified"
    assert enriched[1]["address_source"] == "contact_unverified"
    assert enriched[0]["customer_address"]
    assert calls == 1, f"Expected one cached contact lookup, got {calls}"

    print("GHL contact address remains unverified | PASS")
    print("Repeated contact lookup cached | PASS")

    assert enriched[2].get("customer_address") is None
    print("Missing contact address remains missing | PASS")

    
    assert enriched[3]["address_source"] == "appointment_unverified"
    assert enriched[3]["customer_address"] == (
    "Liberty Bell, Philadelphia, PA"
)
    print("Untrusted service-confirmed label rejected | PASS")
    print("Existing appointment address preserved as unverified | PASS")
 

    neighbor = {
        "previous_appointment": enriched[0],
        "next_appointment": None,
    }

    try:
        await main.calculate_neighbor_travel(
            neighbors=neighbor,
            customer_address="Independence Hall, Philadelphia, PA",
        )
    except MapsServiceError:
        print("Unverified neighboring address rejected | PASS")
    else:
        raise AssertionError(
            "Unverified neighbor address was not rejected"
        )
    # Test: GHL contact lookup fails.
    # No real GHL or Google API requests are made.

    async def failing_contact_lookup(contact_id):
        raise ConnectionError("Simulated GHL connection failure")

    failed_appointments = [
        {
            "groomer_id": "silpa",
            "contact_id": "fictional-failed-contact",
            "customer_address": None,
        }
    ]

    with patch.object(
        main, "get_ghl_contact", failing_contact_lookup
    ):
        failed_result = await main.enrich_appointment_addresses(
            failed_appointments
        )

    failed_appointment = failed_result[0]

    assert failed_appointment["customer_address"] is None
    assert failed_appointment["address_source"] == "contact_unverified"

    print("GHL contact API failure leaves address unverified | PASS")

    try:
        await main.calculate_neighbor_travel(
            neighbors={
                "previous_appointment": failed_appointment,
                "next_appointment": None,
            },
            customer_address="Liberty Bell, Philadelphia, PA",
        )
    except MapsServiceError:
        print("Failed GHL lookup blocks neighbor routing | PASS")
    else:
        raise AssertionError(
            "GHL lookup failure was not safely rejected"
        )
    print("\nGHL address verification safety test | PASS")
    print("Mocked data only. No external API requests.")
    
    # Test: Next appointment has an unverified service address.
    # Must reject routing before calling Google Routes.

    async def forbidden_google_route(*args, **kwargs):
        raise AssertionError(
            "Google Routes must not be called for unverified addresses"
        )

    next_neighbor = {
        "previous_appointment": None,
        "next_appointment": {
            "groomer_id": "silpa",
            "customer_address": "Philadelphia City Hall, Philadelphia, PA",
            "address_source": "contact_unverified",
        },
    }

    with patch.object(
        main, "get_driving_minutes", forbidden_google_route
    ):
        try:
            await main.calculate_neighbor_travel(
                neighbors=next_neighbor,
                customer_address="Liberty Bell, Philadelphia, PA",
            )
        except MapsServiceError:
            print("Unverified next appointment address rejected | PASS")
        else:
            raise AssertionError(
                "Next appointment address was incorrectly accepted"
            )

    # Test: Completely missing next appointment address.
    next_neighbor["next_appointment"]["customer_address"] = None

    with patch.object(
        main, "get_driving_minutes", forbidden_google_route
    ):
        try:
            await main.calculate_neighbor_travel(
                neighbors=next_neighbor,
                customer_address="Liberty Bell, Philadelphia, PA",
            )
        except MapsServiceError:
            print("Missing next appointment address rejected | PASS")
        else:
            raise AssertionError(
                "Missing next appointment address was accepted"
            )



if __name__ == "__main__":
    asyncio.run(run_test())
