"""SS58 addresses: base58 with a blake2b checksum."""

import hashlib

SS58_PREFIX = b"SS58PRE"
CHECKSUM_BYTES = 2
PUBLIC_KEY_BYTES = 32
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class SS58Error(ValueError):
    pass


def b58encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return ALPHABET[0] * leading_zeros + encoded


def b58decode(text: str) -> bytes:
    number = 0
    for char in text:
        index = ALPHABET.find(char)
        if index == -1:
            raise SS58Error(f"invalid base58 character: {char!r}")
        number = number * 58 + index
    leading_zeros = len(text) - len(text.lstrip(ALPHABET[0]))
    body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return b"\x00" * leading_zeros + body


def address_prefix(ss58_format: int) -> bytes:
    if 0 <= ss58_format <= 63:
        return bytes([ss58_format])
    if 64 <= ss58_format <= 16383:
        # Two-byte form, as defined by the SS58 registry.
        low = ((ss58_format & 0b0000_0000_1111_1100) >> 2) | 0b0100_0000
        high = (ss58_format >> 8) | ((ss58_format & 0b0000_0000_0000_0011) << 6)
        return bytes([low, high])
    raise SS58Error(f"unsupported SS58 format: {ss58_format}")


def checksum(payload: bytes) -> bytes:
    return hashlib.blake2b(SS58_PREFIX + payload, digest_size=64).digest()[
        :CHECKSUM_BYTES
    ]


def ss58_encode(public_key: bytes, ss58_format: int) -> str:
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise SS58Error(f"public key must be {PUBLIC_KEY_BYTES} bytes")
    payload = address_prefix(ss58_format) + public_key
    return b58encode(payload + checksum(payload))


def ss58_decode(address: str) -> bytes:
    decoded = b58decode(address)
    if len(decoded) < PUBLIC_KEY_BYTES + CHECKSUM_BYTES + 1:
        raise SS58Error("address is too short")
    payload, given = decoded[:-CHECKSUM_BYTES], decoded[-CHECKSUM_BYTES:]
    if checksum(payload) != given:
        raise SS58Error("address checksum does not match")
    return payload[-PUBLIC_KEY_BYTES:]
