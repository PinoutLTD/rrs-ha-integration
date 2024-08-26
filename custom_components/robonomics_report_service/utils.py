import logging
import os
import random
import shutil
import tempfile
import typing as tp
import json

from os.path import isdir

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from robonomicsinterface import Account
from substrateinterface import Keypair, KeypairType

from .const import LOGS_MAX_LEN, STORAGE_PINATA_CREDS, CONF_PINATA_PUBLIC, CONF_PINATA_SECRET

_LOGGER = logging.getLogger(__name__)

VERSION_STORAGE = 6

def encrypt_message(message, sender_seed: str, recipient_address: str) -> str:
    try:
        random_seed = Keypair.generate_mnemonic()
        random_acc = Account(random_seed, crypto_type=KeypairType.ED25519)
        sender_acc = Account(sender_seed, crypto_type=KeypairType.ED25519)
        sender_keypair = sender_acc.keypair
        encrypted_data = _encrypt_message(
            str(message), sender_keypair, random_acc.keypair.public_key
        )
        devices = [recipient_address, sender_acc.get_address()]
        encrypted_keys = {}
        # _LOGGER.debug(f"Encrypt states for following devices: {devices}")
        for device in devices:
            try:
                receiver_kp = Keypair(
                    ss58_address=device, crypto_type=KeypairType.ED25519
                )
                encrypted_key = _encrypt_message(
                    random_seed, sender_keypair, receiver_kp.public_key
                )
                encrypted_keys[device] = encrypted_key
            except Exception as e:
                _LOGGER.warning(
                    f"Faild to encrypt key for: {device} with error: {e}. Check your RWS devices, you may have SR25519 address in devices."
                )
        encrypted_keys["data"] = encrypted_data
        data_final = json.dumps(encrypted_keys)
        return data_final
    except Exception as e:
        _LOGGER.error(f"Exception in encrypt for devices: {e}")

def _encrypt_message(
    message: tp.Union[bytes, str],
    sender_keypair: Keypair,
    recipient_public_key: bytes,
) -> str:
    """Encrypt message with sender private key and recipient public key

    :param message: Message to encrypt
    :param sender_keypair: Sender account Keypair
    :param recipient_public_key: Recipient public key

    :return: encrypted message
    """
    encrypted = sender_keypair.encrypt_message(message, recipient_public_key)
    return f"0x{encrypted.hex()}"

def decrypt_message(encrypted_message: str, receiver_seed: str, sender_address: str) -> str:
    try:
        data_json = json.loads(encrypted_message)
        recipient_acc = Account(receiver_seed, crypto_type=KeypairType.ED25519)
        sender_kp = Keypair(ss58_address=sender_address)
        if recipient_acc.get_address() in data_json:
            decrypted_seed = _decrypt_message(
                data_json[recipient_acc.get_address()],
                sender_kp.public_key,
                recipient_acc.keypair,
            ).decode("utf-8")
            decrypted_acc = Account(decrypted_seed, crypto_type=KeypairType.ED25519)
            decrypted_data = _decrypt_message(
                data_json["data"], sender_kp.public_key, decrypted_acc.keypair
            ).decode("utf-8")
            return decrypted_data
        else:
            _LOGGER.error(f"Error in decrypt for devices: account is not in devices")
    except Exception as e:
        _LOGGER.error(f"Exception in decrypt for devices: {e}")

def _decrypt_message(
    encrypted_message: str,
    sender_public_key: bytes = None,
    recipient_keypair: Keypair = None,
) -> bytes:
    """Decrypt message with recepient private key and sender puplic key

    :param encrypted_message: Message to decrypt
    :param sender_public_key: Sender public key
    :param recipient_keypair: Recepient account keypair

    :return: Decrypted message
    """
    if encrypted_message[:2] == "0x":
        encrypted_message = encrypted_message[2:]
    bytes_encrypted = bytes.fromhex(encrypted_message)

    return recipient_keypair.decrypt_message(bytes_encrypted, sender_public_key)

def get_address_for_seed(seed: str) -> str:
    acc = Account(seed, crypto_type=KeypairType.ED25519)
    return acc.get_address()

async def pinata_creds_exists(hass: HomeAssistant) -> bool:
    storage_data = await async_load_from_store(hass, STORAGE_PINATA_CREDS)
    res = CONF_PINATA_PUBLIC in storage_data and CONF_PINATA_SECRET in storage_data
    _LOGGER.debug(f"Pinata creds exists: {res}")
    return res


def _get_store_key(key):
    """Return the key to use with homeassistant.helpers.storage.Storage."""
    return f"robonomics.{key}"


def _get_store_for_key(hass, key):
    """Create a Store object for the key."""
    return Store(
        hass,
        VERSION_STORAGE,
        _get_store_key(key),
        encoder=JSONEncoder,
        atomic_writes=True,
    )


async def async_load_from_store(hass, key):
    """Load the retained data from store and return de-serialized data."""
    return await _get_store_for_key(hass, key).async_load() or {}


async def async_remove_store(hass: HomeAssistant, key: str):
    """Remove data from store for given key"""
    await _get_store_for_key(hass, key).async_remove()


async def async_save_to_store(hass, key, data):
    """Generate dynamic data to store and save it to the filesystem.

    The data is only written if the content on the disk has changed
    by reading the existing content and comparing it.

    If the data has changed this will generate two executor jobs

    If the data has not changed this will generate one executor job
    """
    current = await async_load_from_store(hass, key)
    if current is None or current != data:
        await _get_store_for_key(hass, key).async_save(data)
        return
    _LOGGER.debug(f"Content in .storage/{_get_store_key(key)} was't changed")


def create_encrypted_picture(
    data: bytes,
    number_of_picture: int,
    dirname: str,
    sender_seed: tp.Optional[str] = None,
    receiver_address: tp.Optional[str] = None,
) -> str:
    encrypted_data = encrypt_message(data, sender_seed, receiver_address)
    picture_path = f"{dirname}/picture{number_of_picture}"
    with open(picture_path, "w") as f:
        f.write(encrypted_data)
    _LOGGER.debug(f"Created encrypted picture: {picture_path}")
    return picture_path


def create_temp_dir_with_encrypted_files(
    dirname: str,
    files: tp.List[str],
    sender_seed: tp.Optional[str],
    receiver_address: tp.Optional[str],
) -> str:
    """
    Create directory in tepmoral directory and copy there files

    :param dirname: the name of the directory to create
    :param files: list of file pathes to copy

    :return: path to the created directory
    """
    try:
        temp_dirname = tempfile.gettempdir()
        dirpath = f"{temp_dirname}/{dirname}"
        if os.path.exists(dirpath):
            dirpath += str(random.randint(1, 1000))
        try:
            os.mkdir(dirpath)
        except Exception as e:
            _LOGGER.debug(f"Can't create tempdir: {e}, retrying...")
            return create_temp_dir_with_encrypted_files(dirname, files, sender_seed, receiver_address)
        for filepath in files:
            filename = filepath.split("/")[-1]
            if sender_seed and receiver_address:
                with open(filepath, "r") as f:
                    data = f.read()
                data = data[-LOGS_MAX_LEN:]
                encrypted_data = encrypt_message(
                    data, sender_seed, receiver_address
                )
                with open(f"{dirpath}/{filename}", "w") as f:
                    f.write(encrypted_data)
            else:
                shutil.copyfile(filepath, f"{dirpath}/{filename}")
        return dirpath
    except Exception as e:
        _LOGGER.error(f"Exception in create temp dir: {e}")


def delete_temp_dir(dirpath: str) -> None:
    """
    Delete temporary directory

    :param dirpath: the path to the directory
    """
    shutil.rmtree(dirpath)

def get_tempdir_filenames(dirname_prefix: str) -> tp.List[str]:
    temp_dirname = tempfile.gettempdir()
    filenames = os.listdir(temp_dirname)
    temdir_names = []
    for filename in filenames:
        filepath = f"{temp_dirname}/{filename}"
        if isdir(filepath) and filename.startswith(dirname_prefix):
            temdir_names.append(filepath)
    return temdir_names
