
from geographic_eligibility_adapter import (
    validate_geographic_eligibility,
)


def main():
    print("===== PERSON 1 - STEP 7.4 =====")

    groomer = "fictional-groomer-001"

    cases = [
        (
            "Verified eligible groomer",
            {
                "groomer_id": groomer,
                "verification_status": "verified",
                "eligible": True,
            },
            True,
        ),
        (
            "Explicitly ineligible groomer",
            {
                "groomer_id": groomer,
                "verification_status": "verified",
                "eligible": False,
            },
            False,
        ),
        (
            "Unverified territory",
            {
                "groomer_id": groomer,
                "verification_status": "pending",
                "eligible": True,
            },
            False,
        ),
        (
            "Mismatched groomer",
            {
                "groomer_id": "different-groomer",
                "verification_status": "verified",
                "eligible": True,
            },
            False,
        ),
        (
            "Missing evidence",
            None,
            False,
        ),
    ]

    for label, evidence, expected in cases:
        result = validate_geographic_eligibility(
            groomer,
            evidence,
        )

        assert result["eligible"] is expected, result
        assert result["booking_authorized"] is False

        if expected:
            assert result["geographic_verified"] is True
        else:
            assert result["geographic_verified"] is False

        print(label + ": PASS")

    print("Real geographic service called: False")
    print("Live booking authorized: False")
    print("STEP 7.4 PASSED")


if __name__ == "__main__":
    main()
