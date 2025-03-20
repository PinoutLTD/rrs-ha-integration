
from robonomicsinterface import Account
from substrateinterface import Keypair, KeypairType

from custom_components.robonomics_report_service.utils import multi_device_encrypt_message, encrypt_message, decrypt_message, _decrypt_message

sender_address = "4CsXeZy3VbKnB9YMUBYpgsnsaZXZczF2PXH1bYYGBnH5PRcz"
sender_seed = "labor now library worry monitor surface sword pulse poem fee cousin outer"
sender_account = Account(sender_seed, crypto_type=KeypairType.ED25519)

receiver_address = "4FqVtVUCZ1dGSMHAXecNw5AbS4Dib6xZyPPThpDTMdkeXrvp"
receiver_seed = "perfect gorilla main winner amateur lounge glance oval wash advice blouse top"
receiver_account = Account(receiver_seed, crypto_type=KeypairType.ED25519)

message = "Hello, there is the test message!"
message_encrypted = "0xd9e064809422956049513b30ca1ffdf8704090e12981ed3e470364ea9627586d849bd007c6ef39556cff3312649e901cc6a37d0cf9d2fa568f95a4f3958729196fa3d14da382fe46f7"
message_encrypted_for_multiply_devices = {'4FqVtVUCZ1dGSMHAXecNw5AbS4Dib6xZyPPThpDTMdkeXrvp': '0x80fedf4212aa1f3a67f82ebd46bd820baabb0a9d6b7c2914fff46c07ecc0330dc35ad071c50c5331f86ea1fba19eee96a1a6e5a3b207b2b7aa05a5528493b54df7fdde3ad5f11515b8c89b4f7fb0ad0436e5e524df020f377742acfcf1d4563925f5df5b61e658e8ada8f51fdc683958', '4CsXeZy3VbKnB9YMUBYpgsnsaZXZczF2PXH1bYYGBnH5PRcz': '0x80fedf4212aa1f3a67f82ebd46bd820baabb0a9d6b7c29140a89c148ff361396d0394ff1c4817755e127c776f17efc369af32da336bebcb0a82893d304efb92c8e862f795805e068c35a11001d482e94851bf599be472a65f0aea89d310c01f16974f278a84b57a508b55a54a6dc0d5e', 'data': '0x80fedf4212aa1f3a67f82ebd46bd820baabb0a9d6b7c29143479c1ae1a99a10742fff759a275a818e720dcab2a94feeb67b6748b935e2df27aa8a03cbe7b3d03abfe4c182b404116f2'}

def test_decrypt_for_one_acc():
    decrypted = decrypt_message(message_encrypted, receiver_seed, sender_address)
    assert decrypted == message
    
def test_multi_device_encrypt_message_format():
    encrypted = multi_device_encrypt_message(message, sender_seed, receiver_address)
    assert isinstance(encrypted, dict)
    assert sender_address in encrypted
    assert receiver_address in encrypted
    assert "data" in encrypted

def test_multi_device_decrypt():
    decrypted_receiver = decrypt_message(message_encrypted_for_multiply_devices, receiver_seed, sender_address)
    decrypted_sender = decrypt_message(message_encrypted_for_multiply_devices, sender_seed, sender_address)
    assert decrypted_receiver == message
    assert decrypted_sender == message