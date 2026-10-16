
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/New_York")

# Sample schedules copied from GHL's visible availability.
# These are not live calendar or staff API records.

GROOMERS = {
    "ambily": {
        "name": "Ambili Reshma Rajan",
        "start": time(9, 0),
        "end": time(17, 0),
        "depot_address": None
    },
    "john": {
        "name": "John MHD",
        "start": time(8, 0),
        "end": time(17, 0),
        "depot_address": None
    },
    "silpa": {
        "name": "Silpa S Kumar",
        "start": time(9, 0),
        "end": time(17, 0),
        "depot_address": None
    }
}

# Fictional development-only groomer depots.
# These are public landmarks, NOT verified operating locations.
# Never use them for customer-facing availability or live bookings.

DEMO_GROOMER_DEPOTS = {
    "ambily": "Philadelphia City Hall, Philadelphia, PA",
    "john": "Philadelphia Museum of Art, Philadelphia, PA",
    "silpa": "Independence Hall, Philadelphia, PA",
}



def get_groomer_availability(groomer_id: str, date_str: str):
    groomer = GROOMERS.get(groomer_id)

    if groomer is None:
        raise ValueError("Unknown groomer ID")

    selected_date = datetime.strptime(
        date_str, "%Y-%m-%d"
    ).date()

    if selected_date.weekday() >= 5:
        return {
            "groomer": groomer["name"],
            "date": date_str,
            "available": False,
            "reason": "Outside working days"
        }

    start = datetime.combine(
        selected_date, groomer["start"], tzinfo=TIMEZONE
    )
    end = datetime.combine(
        selected_date, groomer["end"], tzinfo=TIMEZONE
    )

    return {
        "groomer": groomer["name"],
        "date": date_str,
        "available": True,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "America/New_York"
    }



from datetime import timedelta


def check_groomer_conflict(
    groomer_id: str,
    requested_start: datetime,
    service_minutes: int,
    appointments: list,
    post_buffer_minutes: int = 15
):
    if groomer_id not in GROOMERS:
        raise ValueError("Unknown groomer ID")

    if requested_start.tzinfo is None:
        raise ValueError("Requested start must include a timezone")

    if service_minutes <= 0 or post_buffer_minutes < 0:
        raise ValueError("Invalid duration or buffer")

    requested_end = requested_start + timedelta(
        minutes=service_minutes + post_buffer_minutes
    )

    for appointment in appointments:
        if appointment["groomer_id"] != groomer_id:
            continue

        existing_start = datetime.fromisoformat(
            appointment["start_time"]
        )
        existing_end = datetime.fromisoformat(
            appointment["end_time"]
        )

        existing_end += timedelta(
         minutes=appointment.get("post_buffer_minutes", 15)
        )

        if existing_start.tzinfo is None or existing_end.tzinfo is None:
            raise ValueError("Appointment timestamps need timezones")

        if (
            requested_start < existing_end
            and existing_start < requested_end
        ):
            return True

    return False



def check_groomer_booking(
    groomer_id: str,
    requested_start: datetime,
    service_minutes: int,
    appointments: list,
    post_buffer_minutes: int = 15
):
    if requested_start.tzinfo is None:
        raise ValueError("Timezone required")

    if service_minutes <= 0 or post_buffer_minutes < 0:
        raise ValueError("Invalid service duration or buffer")

    requested_local = requested_start.astimezone(TIMEZONE)

    schedule = get_groomer_availability(
        groomer_id,
        requested_local.date().isoformat()
    )

    if not schedule["available"]:
        return {
            "groomer_id": groomer_id,
            "available": False,
            "reason": "Outside working days"
        }

    work_start = datetime.fromisoformat(schedule["start"])
    work_end = datetime.fromisoformat(schedule["end"])

    occupied_until = requested_local + timedelta(
        minutes=service_minutes + post_buffer_minutes
    )

    if requested_local < work_start or occupied_until > work_end:
        return {
            "groomer_id": groomer_id,
            "available": False,
            "reason": "Outside working hours"
        }

    conflict = check_groomer_conflict(
        groomer_id=groomer_id,
        requested_start=requested_local,
        service_minutes=service_minutes,
        appointments=appointments,
        post_buffer_minutes=post_buffer_minutes
    )

    return {
        "groomer_id": groomer_id,
        "available": not conflict,
        "reason": (
            "Appointment conflict" if conflict
            else "Available in sample schedule"
        )
    }
