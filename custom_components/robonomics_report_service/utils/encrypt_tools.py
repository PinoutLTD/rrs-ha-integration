"""Report encryption, kept as the integration's own code.

The format and the primitives live in `chain.envelope`, which depends only on
PyNaCl and therefore installs on the boards Home Assistant actually runs on.
This module is what the rest of the integration imports: it keeps the old
names and raises the integration's own exceptions.
"""

from typing import Any

from ..chain import Keypair
from ..chain.envelope import (
    PackageError,
    PayloadError,
    RecipientError,
    decrypt_message,
    decrypt_package,
    encrypt_for_recipients,
    encrypt_message,
    parse_decrypted,
)
from ..exceptions import (
    EnvelopeCryptoDecryptError,
    EnvelopePackageDecryptError,
    EnvelopeRecipientEncryptError,
)

__all__ = [
    "decrypt_msg",
    "encrypt_msg",
    "multi_envelope_decrypt_data",
    "multi_envelope_encrypt_data",
    "parse_decrypted",
]


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


def multi_envelope_decrypt_data(
    encryption_package: str,
    recipient_keypair: Keypair,
    sender_address: str,
) -> str:
    """Unwrap the key addressed to us, then decrypt the payload."""

    try:
        return decrypt_package(encryption_package, recipient_keypair, sender_address)
    except PackageError as e:
        raise EnvelopePackageDecryptError(
            str(e), address=recipient_keypair.ss58_address
        ) from e
    except PayloadError as e:
        raise EnvelopeCryptoDecryptError(str(e)) from e


def encrypt_msg(
    msg: bytes | str,
    sender_keypair: Keypair,
    recipient_public_key: bytes,
) -> str:
    return encrypt_message(msg, sender_keypair, recipient_public_key)


def decrypt_msg(
    encrypted_msg: str,
    sender_public_key: bytes,
    recipient_keypair: Keypair,
) -> bytes:
    return decrypt_message(encrypted_msg, sender_public_key, recipient_keypair)
