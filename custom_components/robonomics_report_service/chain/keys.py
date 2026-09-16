"""ED25519 keys, signatures and message encryption on PyNaCl.

The wire formats are the ones substrate-interface produced, byte for byte:
the same mini secret, the same ed25519 → curve25519 conversion, and the same
NaCl box with the nonce in front. Reports already published to IPFS must stay
readable, and the ones produced here must open with the tools that read the
old ones.
"""

from __future__ import annotations

import nacl.bindings
import nacl.public
import nacl.signing

from .bip39 import generate_mnemonic, mnemonic_to_mini_secret
from .ss58 import ss58_decode, ss58_encode

# Robonomics addresses start with "4".
ROBONOMICS_SS58_FORMAT = 32
NONCE_BYTES = 24
SEED_BYTES = 32


class Keypair:
    """An ED25519 account: the seed stays in memory and never leaves it."""

    def __init__(self, seed: bytes, ss58_format: int = ROBONOMICS_SS58_FORMAT) -> None:
        if len(seed) != SEED_BYTES:
            raise ValueError(f"seed must be {SEED_BYTES} bytes")
        self._signing_key = nacl.signing.SigningKey(seed)
        self.ss58_format = ss58_format
        self.public_key = bytes(self._signing_key.verify_key)

    @classmethod
    def create_from_mnemonic(
        cls,
        mnemonic: str,
        password: str = "",
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
    ) -> Keypair:
        return cls(mnemonic_to_mini_secret(mnemonic, password), ss58_format)

    @classmethod
    def create_from_public_key(
        cls, public_key: bytes, ss58_format: int = ROBONOMICS_SS58_FORMAT
    ) -> Keypair:
        """A counterparty: enough to verify and to encrypt, not to sign."""

        keypair = cls.__new__(cls)
        keypair._signing_key = None
        keypair.ss58_format = ss58_format
        keypair.public_key = public_key
        return keypair

    @classmethod
    def create_from_address(
        cls, address: str, ss58_format: int = ROBONOMICS_SS58_FORMAT
    ) -> Keypair:
        return cls.create_from_public_key(ss58_decode(address), ss58_format)

    @staticmethod
    def generate_mnemonic(word_count: int = 12) -> str:
        return generate_mnemonic(word_count)

    @property
    def ss58_address(self) -> str:
        return ss58_encode(self.public_key, self.ss58_format)

    def _require_secret(self) -> nacl.signing.SigningKey:
        if self._signing_key is None:
            raise ValueError("this keypair holds a public key only")
        return self._signing_key

    def sign(self, message: bytes) -> bytes:
        return self._require_secret().sign(message).signature

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            nacl.signing.VerifyKey(self.public_key).verify(message, signature)
        except Exception:
            return False
        return True

    def _curve25519_secret(self) -> bytes:
        signing_key = self._require_secret()
        return nacl.bindings.crypto_sign_ed25519_sk_to_curve25519(
            bytes(signing_key) + self.public_key
        )

    def encrypt_message(
        self, message: bytes | str, recipient_public_key: bytes
    ) -> bytes:
        """Encrypt for one recipient; the nonce is prepended, as NaCl does."""

        if isinstance(message, str):
            message = message.encode("utf-8")
        sender = nacl.public.PrivateKey(self._curve25519_secret())
        recipient = nacl.public.PublicKey(
            nacl.bindings.crypto_sign_ed25519_pk_to_curve25519(recipient_public_key)
        )
        return bytes(nacl.public.Box(sender, recipient).encrypt(message))

    def decrypt_message(
        self, encrypted_message: bytes, sender_public_key: bytes
    ) -> bytes:
        recipient = nacl.public.PrivateKey(self._curve25519_secret())
        sender = nacl.public.PublicKey(
            nacl.bindings.crypto_sign_ed25519_pk_to_curve25519(sender_public_key)
        )
        return nacl.public.Box(recipient, sender).decrypt(encrypted_message)
