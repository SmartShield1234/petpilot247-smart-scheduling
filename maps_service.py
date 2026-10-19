
import httpx


class MapsServiceError(Exception):
    pass


def parse_route_duration(duration):
    """Convert a Google Routes duration such as '1234s' to minutes."""
    if not isinstance(duration, str) or not duration.endswith("s"):
        raise MapsServiceError("Invalid route duration")

    try:
        seconds = float(duration[:-1])
    except ValueError as exc:
        raise MapsServiceError("Invalid route duration") from exc

    if seconds < 0:
        raise MapsServiceError("Negative route duration")

    import math
    return math.ceil(seconds / 60)


async def get_driving_minutes(
    origin_address,
    destination_address,
    api_key
):
    """Retrieve driving time from Google Routes API."""

    if not origin_address or not destination_address:
        raise MapsServiceError("Origin and destination required")

    if not api_key:
        raise MapsServiceError("Google Maps API key required")

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    payload = {
        "origin": {
            "address": origin_address
        },
        "destination": {
            "address": destination_address
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE"
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters"
    }

 
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code

        try:
            error_data = exc.response.json()
            google_error = error_data.get("error", {})
            error_status = google_error.get("status", "UNKNOWN")
            error_message = google_error.get(
                "message", "No error message provided"
            )
        except (ValueError, AttributeError, TypeError):
            error_status = "UNKNOWN"
            error_message = "Unable to parse Google error response"

        # Do not print the full response or your API key.
        print("Google API HTTP status:", status)
        print("Google API error status:", error_status)
        print("Google API error message:", error_message)

        raise MapsServiceError(
            f"Google Routes HTTP status: {status}"
        ) from exc

    except httpx.RequestError as exc:
        raise MapsServiceError(
            f"Google Routes connection error: {type(exc).__name__}"
        ) from exc


    routes = data.get("routes", [])

    if not routes:
        raise MapsServiceError("No driving route found")

    route = routes[0]

    if "duration" not in route:
        raise MapsServiceError("Route duration missing")

    distance_meters = route.get("distanceMeters")
    print("Route response fields:", sorted(route.keys()))
    print("Distance field present:", "distanceMeters" in route)
    print("Distance value type:", type(distance_meters).__name__)
    print(
        "Distance is numeric:",
        isinstance(distance_meters, (int, float))
        and not isinstance(distance_meters, bool)
    )

    if (
        isinstance(distance_meters, bool)
        or not isinstance(distance_meters, (int, float))
        or not (0 <= distance_meters < float("inf"))
    ):
        raise MapsServiceError(
            "Invalid or missing Google Routes distance"
        )

    return {
        "driving_minutes": parse_route_duration(
            route["duration"]
        ),
        "distance_meters": distance_meters,
    }


def validate_route_addresses(origin_address, destination_address):
    """Check that both route addresses are present and nonempty."""

    if not isinstance(origin_address, str) or not origin_address.strip():
        raise MapsServiceError("Valid origin address required")

    if not isinstance(destination_address, str) or not destination_address.strip():
        raise MapsServiceError("Valid destination address required")

    return {
        "origin": origin_address.strip(),
        "destination": destination_address.strip()
    }
