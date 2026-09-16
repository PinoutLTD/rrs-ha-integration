"""The envelope must stay readable by everything that reads the old reports."""

import json

import pytest
from chain import Keypair, decrypt_package, encrypt_for_recipients, parse_decrypted
from chain.envelope import PackageError, PayloadError, RecipientError

from .test_chain import ACCOUNTS

PAYLOAD = "2026-09-16 13:00:00 ERROR (MainThread) [zha] Failed to connect\n"
META = {"orig_file_name": "home-assistant.log"}


@pytest.fixture
def sender() -> Keypair:
    return Keypair.create_from_mnemonic(ACCOUNTS["sender"]["mnemonic"])


@pytest.fixture
def recipient() -> Keypair:
    return Keypair.create_from_mnemonic(ACCOUNTS["recipient"]["mnemonic"])


def test_recipient_reads_the_payload(sender, recipient) -> None:
    package = encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address])

    assert decrypt_package(package, recipient, sender.ss58_address) == PAYLOAD


def test_sender_can_read_back_its_own_report(sender, recipient) -> None:
    package = encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address])

    assert decrypt_package(package, sender, sender.ss58_address) == PAYLOAD


def test_metadata_travels_with_the_payload(sender, recipient) -> None:
    package = encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address], META)

    payload, meta = parse_decrypted(decrypt_package(package, recipient, sender.ss58_address))

    assert (payload, meta) == (PAYLOAD, META)


def test_package_shape_is_unchanged(sender, recipient) -> None:
    package = json.loads(encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address]))

    assert set(package) == {"data", "keys"}
    assert package["data"].startswith("0x")
    assert set(package["keys"]) == {sender.ss58_address, recipient.ss58_address}
    assert all(key.startswith("0x") for key in package["keys"].values())


def test_each_report_uses_a_new_key(sender, recipient) -> None:
    first = json.loads(encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address]))
    second = json.loads(encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address]))

    assert first["data"] != second["data"]
    assert first["keys"] != second["keys"]


def test_stranger_cannot_open_the_package(sender, recipient) -> None:
    stranger = Keypair.create_from_mnemonic(Keypair.generate_mnemonic())
    package = encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address])

    with pytest.raises(PackageError, match="not addressed"):
        decrypt_package(package, stranger, sender.ss58_address)


def test_wrong_sender_is_a_decryption_failure(sender, recipient) -> None:
    package = encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address])
    other = Keypair.create_from_mnemonic(Keypair.generate_mnemonic())

    with pytest.raises(PayloadError, match="unwrap"):
        decrypt_package(package, recipient, other.ss58_address)


def test_invalid_recipient_address_is_named(sender) -> None:
    with pytest.raises(RecipientError, match="invalid address"):
        encrypt_for_recipients(PAYLOAD, sender, ["not-an-address"])


@pytest.mark.parametrize(
    "package",
    ["not json", "[]", json.dumps({"data": "0x00"}), json.dumps({"keys": {}})],
)
def test_malformed_packages_are_refused(package, recipient, sender) -> None:
    with pytest.raises(PackageError):
        decrypt_package(package, recipient, sender.ss58_address)


def test_damaged_payload_is_refused(sender, recipient) -> None:
    package = json.loads(encrypt_for_recipients(PAYLOAD, sender, [recipient.ss58_address]))
    package["data"] = package["data"][:-2] + "00"

    with pytest.raises(PayloadError, match="payload"):
        decrypt_package(json.dumps(package), recipient, sender.ss58_address)


# Compatibility with the stack that produced the reports already in IPFS


def old_stack_keypair(mnemonic: str):
    from substrateinterface import Keypair as SubstrateKeypair
    from substrateinterface import KeypairType

    return SubstrateKeypair.create_from_mnemonic(
        mnemonic, crypto_type=KeypairType.ED25519, ss58_format=32
    )


def test_the_connector_still_opens_our_packages(sender, recipient) -> None:
    """The connector runs substrate-interface: it must read what we write."""

    old_recipient = old_stack_keypair(ACCOUNTS["recipient"]["mnemonic"])
    package = json.loads(
        encrypt_for_recipients(PAYLOAD, sender, [old_recipient.ss58_address], META)
    )

    from nacl.secret import SecretBox

    wrapped = package["keys"][old_recipient.ss58_address]
    secret_key = old_recipient.decrypt_message(bytes.fromhex(wrapped[2:]), sender.public_key)
    data = SecretBox(secret_key).decrypt(bytes.fromhex(package["data"][2:]))

    payload, meta = parse_decrypted(data.decode("utf-8"))
    assert (payload, meta) == (PAYLOAD, META)


def test_we_open_packages_built_by_the_old_stack(recipient) -> None:
    """A package assembled exactly as the previous implementation did."""

    import secrets

    from nacl.secret import SecretBox

    old_sender = old_stack_keypair(ACCOUNTS["sender"]["mnemonic"])
    secret_key = secrets.token_bytes(32)
    prepared = json.dumps({"payload": PAYLOAD, "meta": META}, ensure_ascii=False)
    package = json.dumps(
        {
            "data": "0x" + bytes(SecretBox(secret_key).encrypt(prepared.encode())).hex(),
            "keys": {
                recipient.ss58_address: "0x"
                + old_sender.encrypt_message(secret_key, recipient.public_key).hex()
            },
        }
    )

    payload, meta = parse_decrypted(decrypt_package(package, recipient, old_sender.ss58_address))
    assert (payload, meta) == (PAYLOAD, META)
