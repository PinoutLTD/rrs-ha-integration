"""BIP39 mnemonics and the seed Substrate actually uses.

Substrate does not take the standard BIP39 seed. It derives a 32-byte "mini
secret" from the mnemonic's *entropy*, not from the mnemonic string, with
PBKDF2-HMAC-SHA512 over 2048 rounds (`substrate-bip39::seed_from_entropy`).
Using the standard seed here would produce a different address and lock the
site out of its own account, which is why the golden vectors in the tests
come from the previous implementation.
"""

import hashlib
import secrets
import unicodedata
from pathlib import Path

WORDLIST_FILE = Path(__file__).with_name("english.txt")
# The canonical BIP39 English wordlist; checked on load so a damaged copy
# cannot silently change derived addresses.
WORDLIST_SHA256 = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"
WORDLIST_SIZE = 2048
PBKDF2_ROUNDS = 2048
MINI_SECRET_BYTES = 32
VALID_WORD_COUNTS = (12, 15, 18, 21, 24)


class MnemonicError(ValueError):
    pass


def _read_wordlist() -> tuple[str, ...]:
    data = WORDLIST_FILE.read_bytes()
    if hashlib.sha256(data).hexdigest() != WORDLIST_SHA256:
        raise MnemonicError("BIP39 wordlist does not match its known checksum")
    words = tuple(data.decode("utf-8").split())
    if len(words) != WORDLIST_SIZE:
        raise MnemonicError(f"BIP39 wordlist has {len(words)} words, expected 2048")
    return words


# Read once, at import. Home Assistant imports integrations off the event
# loop, whereas the first mnemonic is generated inside a config flow step:
# reading the file lazily there is blocking I/O in the loop, which HA flags.
WORDLIST = _read_wordlist()


def load_wordlist() -> tuple[str, ...]:
    return WORDLIST


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text)


def generate_mnemonic(word_count: int = 12) -> str:
    if word_count not in VALID_WORD_COUNTS:
        raise MnemonicError(f"word count must be one of {VALID_WORD_COUNTS}")
    entropy_bits = word_count * 32 // 3
    entropy = secrets.token_bytes(entropy_bits // 8)
    return entropy_to_mnemonic(entropy)


def entropy_to_mnemonic(entropy: bytes) -> str:
    if len(entropy) * 8 not in (128, 160, 192, 224, 256):
        raise MnemonicError(f"invalid entropy length: {len(entropy)} bytes")
    words = load_wordlist()
    checksum_bits = len(entropy) * 8 // 32
    checksum = hashlib.sha256(entropy).digest()[0] >> (8 - checksum_bits)
    bits = int.from_bytes(entropy, "big") << checksum_bits | checksum
    total_bits = len(entropy) * 8 + checksum_bits
    indexes = [
        (bits >> shift) & (WORDLIST_SIZE - 1)
        for shift in range(total_bits - 11, -1, -11)
    ]
    return " ".join(words[index] for index in indexes)


def mnemonic_to_entropy(mnemonic: str) -> bytes:
    """Return the entropy behind a mnemonic, refusing a bad checksum."""

    words = normalize(mnemonic).split()
    if len(words) not in VALID_WORD_COUNTS:
        raise MnemonicError(f"mnemonic has {len(words)} words, expected 12–24")

    wordlist = load_wordlist()
    index_of = {word: index for index, word in enumerate(wordlist)}
    bits = 0
    for word in words:
        if word not in index_of:
            raise MnemonicError(f"word is not in the BIP39 list: {word!r}")
        bits = bits << 11 | index_of[word]

    total_bits = len(words) * 11
    checksum_bits = total_bits // 33
    entropy_bits = total_bits - checksum_bits
    entropy = (bits >> checksum_bits).to_bytes(entropy_bits // 8, "big")
    expected = hashlib.sha256(entropy).digest()[0] >> (8 - checksum_bits)
    if bits & ((1 << checksum_bits) - 1) != expected:
        raise MnemonicError("mnemonic checksum does not match")
    return entropy


def validate_mnemonic(mnemonic: str) -> bool:
    try:
        mnemonic_to_entropy(mnemonic)
    except MnemonicError:
        return False
    return True


def mnemonic_to_mini_secret(mnemonic: str, password: str = "") -> bytes:
    """The 32-byte secret Substrate derives from a mnemonic."""

    entropy = mnemonic_to_entropy(mnemonic)
    salt = ("mnemonic" + normalize(password)).encode("utf-8")
    seed = hashlib.pbkdf2_hmac("sha512", entropy, salt, PBKDF2_ROUNDS, dklen=64)
    return seed[:MINI_SECRET_BYTES]
