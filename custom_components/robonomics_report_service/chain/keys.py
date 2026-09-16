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

# Substrate's MultiSignature/MultiSigner ordering, used both as the value of
# `crypto_type` and as the signature tag inside an extrinsic.
ED25519 = 0
SR25519 = 1
ECDSA = 2
SUPPORTED_CRYPTO_TYPES = (ED25519,)


class UnsupportedCryptoTypeError(ValueError):
    """Raised for a key type the report format cannot use.

    Report encryption converts ed25519 keys to curve25519 on both sides, so
    every account in the chain — the site and the integrator who receives the
    reports — must be ED25519. This is not new: substrate-interface refused
    anything else as well ("Only ed25519 keypair type supported"). Signing
    extrinsics with SR25519 would be possible (py-sr25519-bindings does ship
    aarch64 and musl wheels), but the envelope format would have to change
    first, so the restriction is stated here rather than assumed.
    """


def check_crypto_type(crypto_type: int) -> None:
    if crypto_type not in SUPPORTED_CRYPTO_TYPES:
        raise UnsupportedCryptoTypeError(
            f"crypto type {crypto_type} is not supported: report encryption "
            "requires ED25519 accounts on both sides"
        )


class Keypair:
    """An ED25519 account: the seed stays in memory and never leaves it."""

    def __init__(
        self,
        seed: bytes,
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
        crypto_type: int = ED25519,
    ) -> None:
        check_crypto_type(crypto_type)
        if len(seed) != SEED_BYTES:
            raise ValueError(f"seed must be {SEED_BYTES} bytes")
        self._signing_key = nacl.signing.SigningKey(seed)
        self.ss58_format = ss58_format
        self.crypto_type = crypto_type
        self.public_key = bytes(self._signing_key.verify_key)

    @classmethod
    def create_from_mnemonic(
        cls,
        mnemonic: str,
        password: str = "",
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
        crypto_type: int = ED25519,
    ) -> Keypair:
        return cls(
            mnemonic_to_mini_secret(mnemonic, password), ss58_format, crypto_type
        )

    @classmethod
    def create_from_secret(
        cls,
        secret: str,
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
        crypto_type: int = ED25519,
    ) -> Keypair:
        """Accept what a person may paste: a mnemonic or a raw `0x` seed.

        Development URIs such as `//Alice` are refused on purpose. They are
        well-known keys with well-known secrets, and a client's site must not
        publish its reports from one.
        """

        secret = secret.strip()
        if secret.startswith("//"):
            raise ValueError(
                "development URIs like //Alice are not accepted: the key is public"
            )
        if secret.startswith("0x"):
            try:
                seed = bytes.fromhex(secret[2:])
            except ValueError as e:
                raise ValueError("raw seed is not valid hex") from e
            return cls(seed, ss58_format, crypto_type)
        return cls.create_from_mnemonic(secret, "", ss58_format, crypto_type)

    @classmethod
    def create_from_public_key(
        cls,
        public_key: bytes,
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
        crypto_type: int = ED25519,
    ) -> Keypair:
        """A counterparty: enough to verify and to encrypt, not to sign."""

        check_crypto_type(crypto_type)
        keypair = cls.__new__(cls)
        keypair._signing_key = None
        keypair.ss58_format = ss58_format
        keypair.crypto_type = crypto_type
        keypair.public_key = public_key
        return keypair

    @classmethod
    def create_from_address(
        cls,
        address: str,
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
        crypto_type: int = ED25519,
    ) -> Keypair:
        """Build from an address.

        An SS58 address carries no key type, so an SR25519 account cannot be
        told apart here: it will fail later, when its reports cannot be
        decrypted. Sites are set up by us, which is why the ED25519 rule is
        written down in the README rather than enforced at this point.
        """

        return cls.create_from_public_key(
            ss58_decode(address), ss58_format, crypto_type
        )

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
