"""Storage keys, built the way Substrate builds them."""

import xxhash

EVENTS_PALLET = "System"
EVENTS_ITEM = "Events"


def twox128(name: bytes) -> bytes:
    """Substrate's twox-128: two little-endian xxhash64 digests, seeds 0 and 1."""

    return b"".join(
        xxhash.xxh64(name, seed=seed).digest()[::-1] for seed in (0, 1)
    )


def storage_key(pallet: str, item: str) -> str:
    """The key of a plain storage item, as hex."""

    return "0x" + (twox128(pallet.encode()) + twox128(item.encode())).hex()


def events_key() -> str:
    return storage_key(EVENTS_PALLET, EVENTS_ITEM)
