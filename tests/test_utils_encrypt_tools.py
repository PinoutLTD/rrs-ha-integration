import pytest
from robonomicsinterface import decrypt_package, parse_decrypted

from custom_components.robonomics_report_service.exceptions import (
    EnvelopeRecipientEncryptError,
)
from custom_components.robonomics_report_service.utils.encrypt_tools import (
    multi_envelope_encrypt_data,
)


@pytest.mark.parametrize("data", ["", "hello", "\x00\x01\x02", "строка unicode 👍"])
def test_recipient_and_sender_read_the_report(data, sender_account, recipient_account):
    package = multi_envelope_encrypt_data(data, sender_account, [recipient_account.address])

    for reader in (recipient_account, sender_account):
        assert decrypt_package(package, reader, sender_account.address) == data


def test_metadata_travels_with_the_payload(sender_account, recipient_account):
    meta = {"orig_file_name": "home-assistant.log"}

    package = multi_envelope_encrypt_data(
        "test message", sender_account, [recipient_account.address], meta
    )

    decrypted = decrypt_package(package, recipient_account, sender_account.address)
    assert parse_decrypted(decrypted) == ("test message", meta)


def test_an_invalid_recipient_is_named(sender_account):
    with pytest.raises(EnvelopeRecipientEncryptError, match="not-an-address"):
        multi_envelope_encrypt_data("x", sender_account, ["not-an-address"])
