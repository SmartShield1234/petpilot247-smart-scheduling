
import base64
import binascii
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "ghl_webhook_public_key.pem"


def verify_ghl_webhook_signature(
    raw_body: bytes,
    signature: str | None,
    public_key_path: Path = PUBLIC_KEY_PATH,
) -> bool:
    """
    Verify the HighLevel X-GHL-Signature using Ed25519.

    Return True only for a valid signature.
    No database writes or external API calls.
    """

    if not isinstance(raw_body, bytes):
        return False

    if not signature or not isinstance(signature, str):
        return False

    try:
        signature_bytes = base64.b64decode(
            signature,
            validate=True,
        )

        if len(signature_bytes) != 64:
            return False

        key = load_pem_public_key(
            Path(public_key_path).read_bytes()
        )

        if not isinstance(key, Ed25519PublicKey):
            return False

        key.verify(signature_bytes, raw_body)
        return True

    except (
        InvalidSignature,
        ValueError,
        TypeError,
        binascii.Error,
        OSError,
    ):
        return False
