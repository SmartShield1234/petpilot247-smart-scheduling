
"""Server-side address verification adapter for PetPilot247.

Requires a trusted, server-configured address verification provider.
No provider is configured by default.

Never accept verification evidence directly from an API caller.
"""

from typing import Awaitable, Callable

from geographic_address_validator import validate_confirmed_address


class AddressVerificationUnavailable(RuntimeError):
    pass


AddressProvider = Callable[
    [str],
    Awaitable[dict],
]


class GeographicAddressService:
    def __init__(
        self,
        provider: AddressProvider | None = None,
    ):
        self.provider = provider

    async def verify(self, customer_address: str) -> dict:
        if (
            not isinstance(customer_address, str)
            or len(customer_address.strip()) < 5
        ):
            raise AddressVerificationUnavailable(
                "Invalid customer address"
            )

        if self.provider is None:
            raise AddressVerificationUnavailable(
                "Authenticated address verification provider unavailable"
            )

        try:
            evidence = await self.provider(customer_address)
        except Exception as exc:
            raise AddressVerificationUnavailable(
                "Address verification provider failed"
            ) from exc

        result = validate_confirmed_address(
            customer_address,
            evidence,
        )

        if result["valid"] is not True:
            raise AddressVerificationUnavailable(
                "Customer address could not be verified"
            )

        return result
