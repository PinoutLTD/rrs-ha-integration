import pytest

from custom_components.robonomics_report_service.utils.encrypt_tools import (
    decrypt_msg,
    encrypt_msg,
    multi_envelope_decrypt_data,
    multi_envelope_encrypt_data,
    parse_decrypted,
)


@pytest.mark.parametrize("msg", [
    b"",
    b"hello",
    b"\x00\x01\x02",
    "строка unicode 👍"
    ])
def test_round_trip_simple_msg(msg, sender_account, recipient_account):
    """Test encryption-decryption cycle for several msgs"""
    encrypted_msg = encrypt_msg(
        msg,
        sender_account,
        recipient_account.public_key
    )

    decrypted_msg = decrypt_msg(
        encrypted_msg,
        sender_account.public_key,
        recipient_account
    )

    expected_msg = msg.encode("utf-8") if isinstance(msg, str) else msg
    assert decrypted_msg == expected_msg

@pytest.mark.parametrize("data", [
    "",
    "hello",
    "\x00\x01\x02",
    "строка unicode 👍"
    ])
def test_round_trip_multi_envelope(data, sender_account, recipient_account):
    """Test encryption-decryption cycle for several msgs"""

    recipient_addresses = [recipient_account.ss58_address]

    encrypted_data = multi_envelope_encrypt_data(
        data,
        sender_account,
        recipient_addresses
    )

    decrypted_data_recipient = multi_envelope_decrypt_data(
        encrypted_data,
        recipient_account,
        sender_account.ss58_address
    )

    decrypted_data_sender = multi_envelope_decrypt_data(
        encrypted_data,
        sender_account,
        sender_account.ss58_address
    )

    assert decrypted_data_recipient == decrypted_data_sender == data

def test_round_trip_multi_envelope_with_metadata(
        sender_account,
        recipient_account
        ):
    """Encrypt/decrypt with metadata"""
    payload = "test message"
    meta = {
        "file_name": "test.txt"
    }

    recipient_addresses = [recipient_account.ss58_address]

    encrypted_data = multi_envelope_encrypt_data(
        payload,
        sender_account,
        recipient_addresses,
        meta
    )

    decrypted_data = multi_envelope_decrypt_data(
        encrypted_data,
        recipient_account,
        sender_account.ss58_address
    )

    decrypted_payload, decrypted_meta = parse_decrypted(decrypted_data)

    assert payload == decrypted_payload
    assert meta == decrypted_meta
