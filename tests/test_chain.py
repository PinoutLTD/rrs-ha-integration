"""The new chain primitives must agree with the stack they replace.

`tests/fixtures/substrate_vectors.json` was produced by substrate-interface:
the same mnemonics, the same derived secret, the same address. An address
that differs by one byte is a site locked out of its own account, so these
comparisons are the point of the whole rewrite.
"""

import json
from pathlib import Path

import pytest
from chain import (
    Keypair,
    generate_mnemonic,
    mnemonic_to_mini_secret,
    ss58_decode,
    ss58_encode,
    validate_mnemonic,
)
from chain.bip39 import MnemonicError, entropy_to_mnemonic, mnemonic_to_entropy
from chain.ss58 import SS58Error

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "substrate_vectors.json").read_text("utf-8")
)
ACCOUNTS = {account["name"]: account for account in VECTORS["accounts"]}


@pytest.fixture(params=list(ACCOUNTS))
def account(request) -> dict:
    return ACCOUNTS[request.param]


def test_mini_secret_matches_the_previous_stack(account) -> None:
    # Substrate derives this from the entropy, not from the mnemonic string.
    assert mnemonic_to_mini_secret(account["mnemonic"]).hex() == (
        account["mini_secret_hex"]
    )


def test_public_key_and_address_match(account) -> None:
    keypair = Keypair.create_from_mnemonic(account["mnemonic"])

    assert keypair.public_key.hex() == account["public_key_hex"]
    assert keypair.ss58_address == account["account_address"]


def test_generic_substrate_format_matches(account) -> None:
    keypair = Keypair.create_from_mnemonic(account["mnemonic"], ss58_format=42)

    assert keypair.ss58_address == account["ss58_address"]


def test_address_round_trip(account) -> None:
    assert ss58_decode(account["account_address"]).hex() == account["public_key_hex"]
    assert (
        ss58_encode(bytes.fromhex(account["public_key_hex"]), 32)
        == account["account_address"]
    )


def test_damaged_address_is_refused(account) -> None:
    address = account["account_address"]
    broken = address[:-2] + ("aa" if not address.endswith("aa") else "bb")

    with pytest.raises(SS58Error, match="checksum"):
        ss58_decode(broken)


def test_signature_from_the_previous_stack_verifies() -> None:
    sender = Keypair.create_from_mnemonic(ACCOUNTS["sender"]["mnemonic"])
    signature = bytes.fromhex(VECTORS["signature"]["signature_hex"])

    assert sender.verify(VECTORS["signature"]["message_utf8"].encode(), signature)
    assert sender.sign(VECTORS["signature"]["message_utf8"].encode()) == signature


def test_message_from_the_previous_stack_decrypts() -> None:
    sender = Keypair.create_from_mnemonic(ACCOUNTS["sender"]["mnemonic"])
    recipient = Keypair.create_from_mnemonic(ACCOUNTS["recipient"]["mnemonic"])

    decrypted = recipient.decrypt_message(
        bytes.fromhex(VECTORS["encryption"]["encrypted_hex"]), sender.public_key
    )

    assert decrypted.decode() == VECTORS["encryption"]["plaintext_utf8"]


def test_encryption_round_trip_with_a_fresh_nonce() -> None:
    sender = Keypair.create_from_mnemonic(ACCOUNTS["sender"]["mnemonic"])
    recipient = Keypair.create_from_address(ACCOUNTS["recipient"]["account_address"])
    full_recipient = Keypair.create_from_mnemonic(ACCOUNTS["recipient"]["mnemonic"])

    first = sender.encrypt_message("report", recipient.public_key)
    second = sender.encrypt_message("report", recipient.public_key)

    assert first != second, "each message must carry its own nonce"
    assert full_recipient.decrypt_message(first, sender.public_key) == b"report"


def test_public_only_keypair_cannot_sign() -> None:
    recipient = Keypair.create_from_address(ACCOUNTS["recipient"]["account_address"])

    with pytest.raises(ValueError, match="public key only"):
        recipient.sign(b"nope")


def test_generated_mnemonics_are_valid_and_unique() -> None:
    first, second = generate_mnemonic(), generate_mnemonic()

    assert first != second
    assert len(first.split()) == 12
    assert validate_mnemonic(first)
    assert Keypair.create_from_mnemonic(first).ss58_address.startswith("4")


@pytest.mark.parametrize("word_count", [12, 15, 18, 21, 24])
def test_entropy_round_trip(word_count: int) -> None:
    mnemonic = generate_mnemonic(word_count)

    assert entropy_to_mnemonic(mnemonic_to_entropy(mnemonic)) == mnemonic


def test_broken_mnemonics_are_refused() -> None:
    words = ACCOUNTS["sender"]["mnemonic"].split()

    assert not validate_mnemonic(" ".join(words[:-1]))
    assert not validate_mnemonic(" ".join(words[:-1] + ["zoo"]))
    assert not validate_mnemonic(" ".join(words[:-1] + ["notaword"]))
    with pytest.raises(MnemonicError, match="checksum"):
        mnemonic_to_entropy(" ".join(words[:-1] + ["zoo"]))


def test_the_previous_stack_reads_what_the_new_code_writes() -> None:
    """The connector still runs substrate-interface: it must open our archives."""

    from substrateinterface import Keypair as SubstrateKeypair
    from substrateinterface import KeypairType

    sender = Keypair.create_from_mnemonic(ACCOUNTS["sender"]["mnemonic"])
    old_recipient = SubstrateKeypair.create_from_mnemonic(
        ACCOUNTS["recipient"]["mnemonic"], crypto_type=KeypairType.ED25519
    )

    encrypted = sender.encrypt_message("fresh report", old_recipient.public_key)

    assert (
        old_recipient.decrypt_message(encrypted, sender.public_key).decode()
        == "fresh report"
    )


def test_the_new_code_reads_what_the_previous_stack_writes() -> None:
    from substrateinterface import Keypair as SubstrateKeypair
    from substrateinterface import KeypairType

    old_sender = SubstrateKeypair.create_from_mnemonic(
        ACCOUNTS["sender"]["mnemonic"], crypto_type=KeypairType.ED25519
    )
    recipient = Keypair.create_from_mnemonic(ACCOUNTS["recipient"]["mnemonic"])

    encrypted = old_sender.encrypt_message("old report", recipient.public_key)

    assert (
        recipient.decrypt_message(encrypted, old_sender.public_key).decode()
        == "old report"
    )
