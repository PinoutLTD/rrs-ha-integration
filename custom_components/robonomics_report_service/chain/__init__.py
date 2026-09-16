"""Chain primitives without native bindings.

Replaces robonomics-interface/substrate-interface, whose Rust dependencies
have no wheels for aarch64 or musl on current Python, which is exactly where
Home Assistant runs: Raspberry Pi and HA Green.
"""

from .bip39 import MnemonicError, generate_mnemonic, mnemonic_to_mini_secret, validate_mnemonic
from .envelope import (
    EnvelopeError,
    PackageError,
    PayloadError,
    RecipientError,
    decrypt_package,
    encrypt_for_recipients,
    parse_decrypted,
)
from .keys import ECDSA, ED25519, SR25519, Keypair, UnsupportedCryptoTypeError
from .ss58 import ss58_decode, ss58_encode

__all__ = [
    "ECDSA",
    "MnemonicError",
    "EnvelopeError",
    "PackageError",
    "PayloadError",
    "RecipientError",
    "decrypt_package",
    "encrypt_for_recipients",
    "parse_decrypted",
    "ED25519",
    "SR25519",
    "Keypair",
    "UnsupportedCryptoTypeError",
    "generate_mnemonic",
    "mnemonic_to_mini_secret",
    "ss58_decode",
    "ss58_encode",
    "validate_mnemonic",
]
