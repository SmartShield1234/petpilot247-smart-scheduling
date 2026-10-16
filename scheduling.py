
from datetime import datetime, timedelta


def check_appointment_slot(
    previous_end: datetime,
    next_start: datetime,
    travel_before: int,
    grooming_duration: int,
    setup_time: int,
    cleanup_time: int,
    travel_after: int,
    post_buffer: int = 0
):
    required_minutes = (
        travel_before
        + setup_time
        + grooming_duration
        + cleanup_time
        + post_buffer
        + travel_after
    )

    available_minutes = (
        next_start - previous_end
    ).total_seconds() / 60

    grooming_start = previous_end + timedelta(
        minutes=travel_before + setup_time
    )

    grooming_end = grooming_start + timedelta(
        minutes=grooming_duration
    )

    return {
        "available": required_minutes <= available_minutes,
        "required_minutes": required_minutes,
        "available_minutes": available_minutes,
        "grooming_start": grooming_start.isoformat(),
        "grooming_end": grooming_end.isoformat()
    }



def generate_candidate_slots(
    work_start: datetime,
    work_end: datetime,
    grooming_duration: int = 90,
    interval_minutes: int = 15
):
    if interval_minutes <= 0 or grooming_duration <= 0:
        raise ValueError("Duration and interval must be positive")

    slots = []
    current = work_start

    while current + timedelta(minutes=grooming_duration) <= work_end:
        end_time = current + timedelta(minutes=grooming_duration)

        slots.append({
            "start_time": current.isoformat(),
            "end_time": end_time.isoformat()
        })

        current += timedelta(minutes=interval_minutes)

    return slots


def filter_conflicting_slots(
    candidate_slots: list,
    existing_appointments: list,
    post_buffer_minutes: int = 15,
    work_end: datetime | None = None
):
    valid_slots = []

    for slot in candidate_slots:
        slot_start = datetime.fromisoformat(
            slot["start_time"]
        )
        slot_end = datetime.fromisoformat(
            slot["end_time"]
        ) + timedelta(minutes=post_buffer_minutes)

  # Reject slots extending beyond working hours
        if work_end is not None and slot_end > work_end:
            continue

        conflict = False

        for appointment in existing_appointments:
            appointment_start = datetime.fromisoformat(
                appointment["start_time"]
            )
            appointment_end = datetime.fromisoformat(
                appointment["end_time"]
            ) + timedelta(minutes=post_buffer_minutes)

            if (
                slot_start < appointment_end
                and slot_end > appointment_start
            ):
                conflict = True
                break

        if not conflict:
            valid_slots.append(slot)

    return valid_slots



def validate_travel_slot(
    previous_end: datetime,
    next_start: datetime,
    proposed_start: datetime,
    grooming_duration: int = 90,
    travel_before: int = 20,
    travel_after: int = 25,
    setup_time: int = 10,
    cleanup_time: int = 10,
    post_buffer: int = 15
):
    if min(
        grooming_duration,
        travel_before,
        travel_after,
        setup_time,
        cleanup_time,
        post_buffer
    ) < 0:
        raise ValueError("Durations cannot be negative")

    proposed_end = proposed_start + timedelta(
        minutes=grooming_duration
    )

    earliest_start = previous_end + timedelta(
        minutes=travel_before + setup_time
    )

    ready_for_next = proposed_end + timedelta(
        minutes=cleanup_time + post_buffer + travel_after
    )

    valid = (
        proposed_start >= earliest_start
        and ready_for_next <= next_start
    )

    return {
        "valid": valid,
        "proposed_start": proposed_start.isoformat(),
        "proposed_end": proposed_end.isoformat(),
        "earliest_start": earliest_start.isoformat(),
        "ready_for_next": ready_for_next.isoformat(),
        "next_appointment": next_start.isoformat()
    }



def filter_travel_aware_slots(
    candidate_slots: list,
    existing_appointments: list,
    grooming_duration: int = 90,
    travel_before: int = 20,
    travel_after: int = 25,
    setup_time: int = 10,
    cleanup_time: int = 10,
    post_buffer: int = 15,
    work_start: datetime | None = None,
    work_end: datetime | None = None
):
    if not existing_appointments:
        raise ValueError(
            "This demo requires existing appointments"
        )

    appointments = sorted(
        existing_appointments,
        key=lambda a: a["start_time"]
    )

    valid_slots = []

    for slot in candidate_slots:
        proposed_start = datetime.fromisoformat(
            slot["start_time"]
        )
        proposed_end = datetime.fromisoformat(
            slot["end_time"]
        )

        previous = None
        following = None
        overlaps = False

        for appointment in appointments:
            start = datetime.fromisoformat(
                appointment["start_time"]
            )
            end = datetime.fromisoformat(
                appointment["end_time"]
            )

            if start < proposed_end and end > proposed_start:
                overlaps = True
                break

            if end <= proposed_start:
                previous = appointment
            elif start >= proposed_end and following is None:
                following = appointment

        if overlaps:
            continue

        earliest = (
            datetime.fromisoformat(previous["end_time"])
            + timedelta(minutes=post_buffer + travel_before + setup_time)
            if previous
            else work_start + timedelta(
                minutes=travel_before + setup_time
            )
            if work_start else proposed_start
        )

        ready = proposed_end + timedelta(
            minutes=cleanup_time + post_buffer + travel_after
        )

        deadline = (
            datetime.fromisoformat(following["start_time"])
            if following else work_end
        )

        if proposed_start < earliest:
            continue

        if deadline is None or ready > deadline:
            continue

        valid_slots.append(slot)

    return valid_slots



def rank_appointment_slots(
    valid_slots: list,
    preferred_time: datetime,
    max_results: int = 5
):
    if max_results <= 0:
        raise ValueError("max_results must be positive")

    ranked = []

    for slot in valid_slots:
        start = datetime.fromisoformat(slot["start_time"])

        preference_difference = abs(
            (start - preferred_time).total_seconds()
        ) / 60

        ranked.append({
            **slot,
            "preference_difference_minutes": preference_difference
        })

    ranked.sort(
        key=lambda slot: (
            slot["preference_difference_minutes"],
            slot["start_time"]
        )
    )

    return ranked[:max_results]



from datetime import datetime, timedelta


def check_travel_gap(
    previous_end: datetime,
    proposed_start: datetime,
    post_buffer_minutes: int = 15,
    driving_minutes: int = 20
):
    if previous_end.tzinfo is None or proposed_start.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")

    if post_buffer_minutes < 0 or driving_minutes < 0:
        raise ValueError("Travel and buffer minutes cannot be negative")

    earliest_start = previous_end + timedelta(
        minutes=post_buffer_minutes + driving_minutes
    )

    return {
        "valid": proposed_start >= earliest_start,
        "earliest_start": earliest_start.isoformat(),
        "proposed_start": proposed_start.isoformat()
    }



def check_two_way_travel(
    previous_end,
    proposed_start,
    service_minutes,
    next_start,
    before_drive_minutes,
    after_drive_minutes,
    previous_buffer_minutes=15,
    proposed_buffer_minutes=15
):
    if any(
        value < 0 for value in [
            service_minutes,
            before_drive_minutes,
            after_drive_minutes,
            previous_buffer_minutes,
            proposed_buffer_minutes
        ]
    ):
        raise ValueError("Durations cannot be negative")

    for value in (previous_end, proposed_start, next_start):
        if value.tzinfo is None:
            raise ValueError("Timezone-aware dates required")

    earliest_start = previous_end + timedelta(
        minutes=previous_buffer_minutes + before_drive_minutes
    )

    proposed_end = proposed_start + timedelta(
        minutes=service_minutes
    )

    ready_for_next = proposed_end + timedelta(
        minutes=proposed_buffer_minutes + after_drive_minutes
    )

    return {
        "valid_before": proposed_start >= earliest_start,
        "valid_after": ready_for_next <= next_start,
        "valid": (
            proposed_start >= earliest_start
            and ready_for_next <= next_start
        ),
        "earliest_start": earliest_start.isoformat(),
        "ready_for_next": ready_for_next.isoformat()
    }



def evaluate_groomer_candidates(
    groomer_ids,
    requested_start,
    service_minutes,
    appointments,
    travel_times,
    previous_end,
    next_start,
    post_buffer_minutes=15
):
    from groomers import check_groomer_booking

    results = []

    for groomer_id in groomer_ids:
        booking = check_groomer_booking(
            groomer_id=groomer_id,
            requested_start=requested_start,
            service_minutes=service_minutes,
            appointments=appointments,
            post_buffer_minutes=post_buffer_minutes
        )

        if groomer_id not in travel_times:
            results.append({
                "groomer_id": groomer_id,
                "available": False,
                "reason": "Missing travel-time data"
            })
            continue

        before_drive, after_drive = travel_times[groomer_id]

        travel = check_two_way_travel(
            previous_end=previous_end,
            proposed_start=requested_start,
            service_minutes=service_minutes,
            next_start=next_start,
            before_drive_minutes=before_drive,
            after_drive_minutes=after_drive,
            proposed_buffer_minutes=post_buffer_minutes
        )

        available = booking["available"] and travel["valid"]

        results.append({
            "groomer_id": groomer_id,
            "available": available,
            "booking_valid": booking["available"],
            "travel_valid": travel["valid"],
            "reason": (
                "Available"
                if available
                else (
                    booking["reason"]
                    if not booking["available"]
                    else "Insufficient travel time"
                )
            )
        })

    return results



def find_neighboring_appointments(
    groomer_id,
    requested_start,
    service_minutes,
    appointments
):
    from datetime import datetime, timedelta

    if requested_start.tzinfo is None:
        raise ValueError("Timezone-aware start required")

    if service_minutes <= 0:
        raise ValueError("Invalid service duration")

    proposed_end = requested_start + timedelta(
        minutes=service_minutes
    )

    previous = None
    next_appointment = None
    overlaps = False

    for appointment in appointments:
        if appointment["groomer_id"] != groomer_id:
            continue

        start = datetime.fromisoformat(
            appointment["start_time"]
        )
        end = datetime.fromisoformat(
            appointment["end_time"]
        )

        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Appointment timezone missing")


        if end <= requested_start:
            if previous is None or end > previous["end"]:
                previous = {
                    "start": start,
                    "end": end,
                    "appointment_id": appointment.get("appointment_id"),
                    "customer_address": appointment.get("customer_address"),
                    "address_source": appointment.get("address_source")
                }


        elif start >= proposed_end:
            if (
                next_appointment is None
                or start < next_appointment["start"]
            ):

                next_appointment = {
                    "start": start,
                    "end": end,
                    "appointment_id": appointment.get("appointment_id"),
                    "customer_address": appointment.get("customer_address"),
                    "address_source": appointment.get("address_source")
                }


        else:
            overlaps = True


    return {
        "groomer_id": groomer_id,
        "previous_end": (
            previous["end"].isoformat()
            if previous else None
        ),
        "next_start": (
            next_appointment["start"].isoformat()
            if next_appointment else None
        ),
        "overlaps": overlaps,
        "previous_appointment": previous,
        "next_appointment": next_appointment
    }




def validate_neighbor_travel_data(
    has_previous,
    has_next,
    before_drive_minutes=None,
    after_drive_minutes=None,
    depot_required=False,
    depot_drive_minutes=None
):
    if has_previous and before_drive_minutes is None:
        return {
            "valid": False,
            "reason": "Missing previous-customer travel time"
        }

    if has_next and after_drive_minutes is None:
        return {
            "valid": False,
            "reason": "Missing next-customer travel time"
        }

    if not has_previous and depot_required and depot_drive_minutes is None:
        return {
            "valid": False,
            "reason": "Missing depot travel time"
        }

    durations = [
        value for value in (
            before_drive_minutes if has_previous else None,
            after_drive_minutes if has_next else None,
            depot_drive_minutes if (not has_previous and depot_required) else None
        )
        if value is not None
    ]

    if any(value < 0 for value in durations):
        return {
            "valid": False,
            "reason": "Negative travel duration"
        }

    return {
        "valid": True,
        "reason": "Required travel information available"
    }



def evaluate_safe_groomer_booking(
    groomer_id,
    requested_start,
    service_minutes,
    appointments,
    before_drive_minutes=None,
    after_drive_minutes=None,
    post_buffer_minutes=15,
    depot_required=False,
    depot_drive_minutes=None
):
    from datetime import datetime, timedelta
    from groomers import check_groomer_booking

    neighbors = find_neighboring_appointments(
        groomer_id=groomer_id,
        requested_start=requested_start,
        service_minutes=service_minutes,
        appointments=appointments
    )

    booking = check_groomer_booking(
        groomer_id=groomer_id,
        requested_start=requested_start,
        service_minutes=service_minutes,
        appointments=appointments,
        post_buffer_minutes=post_buffer_minutes
    )

    if not booking["available"] or neighbors["overlaps"]:
        return {
            "groomer_id": groomer_id,
            "available": False,
            "reason": "Appointment conflict or unavailable hours"
        }

    has_previous = neighbors["previous_end"] is not None
    has_next = neighbors["next_start"] is not None

    travel_data = validate_neighbor_travel_data(
        has_previous=has_previous,
        has_next=has_next,
        before_drive_minutes=before_drive_minutes,
        after_drive_minutes=after_drive_minutes,
        depot_required=depot_required,
        depot_drive_minutes=depot_drive_minutes
    )

    if not travel_data["valid"]:
        return {
            "groomer_id": groomer_id,
            "available": False,
            "reason": travel_data["reason"]
        }

    # Check travel from depot to first customer
    if not has_previous and depot_required:
        from groomers import get_groomer_availability

        groomer_schedule = get_groomer_availability(
            groomer_id,
            requested_start.date().isoformat()
        )

        if not groomer_schedule["available"]:
            return {
                "groomer_id": groomer_id,
                "available": False,
                "reason": "Groomer unavailable on selected date"
            }

        work_start = datetime.fromisoformat(
            groomer_schedule["start"]
        )

        earliest_arrival = work_start + timedelta(
            minutes=depot_drive_minutes
        )

        if requested_start < earliest_arrival:
            return {
                "groomer_id": groomer_id,
                "available": False,
                "reason": "Insufficient depot travel time"
            }

    proposed_end = requested_start + timedelta(
        minutes=service_minutes
    )

    if has_previous:
        previous_end = datetime.fromisoformat(
            neighbors["previous_end"]
        )

        earliest_start = previous_end + timedelta(
            minutes=post_buffer_minutes + before_drive_minutes
        )

        if requested_start < earliest_start:
            return {
                "groomer_id": groomer_id,
                "available": False,
                "reason": "Insufficient travel time before booking"
            }

    if has_next:
        next_start = datetime.fromisoformat(
            neighbors["next_start"]
        )

        ready_for_next = proposed_end + timedelta(
            minutes=post_buffer_minutes + after_drive_minutes
        )

        if ready_for_next > next_start:
            return {
                "groomer_id": groomer_id,
                "available": False,
                "reason": "Insufficient travel time after booking"
            }

    return {
        "groomer_id": groomer_id,
        "available": True,
        "reason": "Booking and neighbor travel checks passed"
    }
