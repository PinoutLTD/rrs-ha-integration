"""Report encryption: robonomics-interface's envelope, with our own exception.

The integration only encrypts; the connector decrypts. The format — one
SecretBox payload, its key wrapped for every recipient — is the library's
`encrypt_for_recipients`, the same one the connector's `decrypt_package` opens.
"""

from typing import Any

from robonomicsinterface import Keypair, RecipientError, encrypt_for_recipients

from ..exceptions import EnvelopeRecipientEncryptError

__all__ = ["multi_envelope_encrypt_data"]


def multi_envelope_encrypt_data(
    data: str,
    sender_keypair: Keypair,
    recipient_addresses: list[str],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Encrypt the data once and wrap its key for every recipient."""

    try:
        return encrypt_for_recipients(
            data, sender_keypair, recipient_addresses, metadata
        )
    except RecipientError as e:
        address, _, reason = str(e).partition(": ")
        raise EnvelopeRecipientEncryptError(
            address, reason or "encryption failed"
        ) from e
