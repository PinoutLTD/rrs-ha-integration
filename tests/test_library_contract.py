"""What the integration relies on from robonomics-interface, pinned by vectors.

`tests/fixtures/substrate_vectors.json` was produced by substrate-interface, the
stack that created the sites' keys and encrypted the reports already on IPFS.
The same mnemonic must give the same address, and what the old stack encrypted
must still open: a site locked out of its own account, or reports nobody can
read, would be the cost of getting this wrong.
"""

import json
from pathlib import Path

import pytest
from robonomicsinterface import (
    Keypair,
    decrypt_package,
    encode_address,
    encrypt_for_recipients,
    parse_decrypted,
)

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "substrate_vectors.json").read_text("utf-8")
)
ACCOUNTS = {account["name"]: account for account in VECTORS["accounts"]}


@pytest.fixture(params=[name for name, a in ACCOUNTS.items() if a["valid"]])
def account(request) -> dict:
    return ACCOUNTS[request.param]


def test_the_same_mnemonic_gives_the_same_account(account) -> None:
    keypair = Keypair.from_secret(account["mnemonic"])

    assert keypair.public_key.hex() == account["public_key_hex"].removeprefix("0x")
    assert keypair.address == account["account_address"]
    assert encode_address(keypair.public_key, account["ss58_format"]) == account["ss58_address"]


def test_a_signature_from_the_old_stack_verifies() -> None:
    sender = Keypair.from_secret(ACCOUNTS["sender"]["mnemonic"])
    message = VECTORS["signature"]["message_utf8"].encode()
    signature = bytes.fromhex(VECTORS["signature"]["signature_hex"].removeprefix("0x"))

    assert sender.verify(message, signature)


def test_a_message_from_the_old_stack_decrypts() -> None:
    sender = Keypair.from_secret(ACCOUNTS["sender"]["mnemonic"])
    recipient = Keypair.from_secret(ACCOUNTS["recipient"]["mnemonic"])
    encrypted = bytes.fromhex(VECTORS["encryption"]["encrypted_hex"].removeprefix("0x"))

    decrypted = recipient.decrypt_message(encrypted, sender.public_key)

    assert decrypted.decode() == VECTORS["encryption"]["plaintext_utf8"]


def test_the_report_package_keeps_the_shape_the_connector_reads() -> None:
    sender = Keypair.from_secret(ACCOUNTS["sender"]["mnemonic"])
    recipient = Keypair.from_secret(ACCOUNTS["recipient"]["mnemonic"])
    meta = {"orig_file_name": "home-assistant.log"}

    package = encrypt_for_recipients("log line\n", sender, [recipient.address], meta)
    parsed = json.loads(package)

    assert set(parsed) == {"data", "keys"}
    assert set(parsed["keys"]) == {sender.address, recipient.address}
    assert parse_decrypted(decrypt_package(package, recipient, sender.address)) == (
        "log line\n",
        meta,
    )
