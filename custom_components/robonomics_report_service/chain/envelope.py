"""The report envelope: one symmetric key, wrapped for every recipient.

The payload is encrypted once with a random key, and that key is then
encrypted separately for each address that may open the report. The format is
the one already published to IPFS — `{"data": "0x…", "keys": {address: "0x…"}}`
— and it must stay readable by the tools that read the old reports.
"""

import json
import secrets
from typing import Any

from nacl.secret import SecretBox

from .keys import Keypair
from .ss58 import SS58Error

SECRET_KEY_BYTES = 32


class EnvelopeError(RuntimeError):
    pass


class RecipientError(EnvelopeError):
    """A recipient address cannot be used to wrap the key."""


class PackageError(EnvelopeError):
    """The package is malformed, or not addressed to this recipient."""


class PayloadError(EnvelopeError):
    """The package is well formed but could not be decrypted."""


def encrypt_message(
    message: bytes | str, sender: Keypair, recipient_public_key: bytes
) -> str:
    return "0x" + sender.encrypt_message(message, recipient_public_key).hex()


def decrypt_message(
    encrypted_message: str, sender_public_key: bytes, recipient: Keypair
) -> bytes:
    payload = encrypted_message.removeprefix("0x")
    return recipient.decrypt_message(bytes.fromhex(payload), sender_public_key)


def encrypt_for_recipients(
    data: str,
    sender: Keypair,
    recipient_addresses: list[str],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Encrypt once, wrap the key for each recipient and for the sender."""

    if metadata is not None:
        data = json.dumps({"payload": data, "meta": metadata}, ensure_ascii=False)

    secret_key = secrets.token_bytes(SECRET_KEY_BYTES)
    encrypted_data = SecretBox(secret_key).encrypt(data.encode("utf-8"))

    # The sender is always a recipient: a site can read back what it sent.
    addresses = set(recipient_addresses) | {sender.ss58_address}
    keys: dict[str, str] = {}

    for address in sorted(addresses):
        try:
            recipient = Keypair.create_from_address(address)
        except (SS58Error, ValueError) as e:
            raise RecipientError(f"{address}: invalid address") from e
        try:
            keys[address] = encrypt_message(secret_key, sender, recipient.public_key)
        except Exception as e:
            raise RecipientError(f"{address}: secret key wrap failed") from e

    return json.dumps({"data": "0x" + bytes(encrypted_data).hex(), "keys": keys})


def decrypt_package(package: str, recipient: Keypair, sender_address: str) -> str:
    """Unwrap the key addressed to this recipient, then decrypt the payload."""

    try:
        parsed = json.loads(package)
        encrypted_keys = parsed["keys"]
        encrypted_data = parsed["data"]
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        raise PackageError("invalid encryption package") from e

    if not isinstance(encrypted_keys, dict) or not isinstance(encrypted_data, str):
        raise PackageError("invalid encryption package structure")

    encrypted_secret_key = encrypted_keys.get(recipient.ss58_address)
    if not encrypted_secret_key:
        raise PackageError(f"package is not addressed to {recipient.ss58_address}")

    try:
        sender = Keypair.create_from_address(sender_address)
        secret_key = decrypt_message(
            encrypted_secret_key, sender.public_key, recipient
        )
    except Exception as e:
        raise PayloadError("cannot unwrap the secret key") from e

    try:
        data = SecretBox(secret_key).decrypt(bytes.fromhex(encrypted_data[2:]))
        return data.decode("utf-8")
    except Exception as e:
        raise PayloadError("cannot decrypt the payload") from e


def parse_decrypted(text: str) -> tuple[str, dict | None]:
    """Split `{"payload": …, "meta": …}`, or return plain data without meta."""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text, None
    if isinstance(parsed, dict) and "payload" in parsed:
        meta = parsed.get("meta")
        return parsed["payload"], meta if isinstance(meta, dict) else None
    return text, None
