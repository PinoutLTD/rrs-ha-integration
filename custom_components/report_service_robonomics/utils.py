import asyncio
import functools
import logging
import os
import random
import shutil
import tempfile
import typing as tp

from homeassistant.components.persistent_notification import DOMAIN as NOTIFY_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from robonomicsinterface import Account
from substrateinterface import Keypair, KeypairType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

VERSION_STORAGE = 6
SERVICE_PERSISTENT_NOTIFICATION = "create"


def encrypt_message(
    message: tp.Union[bytes, str],
    sender_keypair: Keypair = None,
    recipient_public_key: bytes = None,
    sender_seed: str = None,
    recipient_address: str = None,
) -> str:
    """Encrypt message with sender private key and recipient public key

    :param message: Message to encrypt
    :param sender_keypair: Sender account Keypair
    :param recipient_public_key: Recipient public key

    :return: encrypted message
    """
    if sender_keypair is None:
        sender_keypair = Account(sender_seed, crypto_type=KeypairType.ED25519).keypair
    if recipient_public_key is None:
        recipient_public_key = Keypair(
            ss58_address=recipient_address, crypto_type=KeypairType.ED25519
        ).public_key
    encrypted = sender_keypair.encrypt_message(message, recipient_public_key)
    return f"0x{encrypted.hex()}"


def decrypt_message(encrypted_message: str, sender_public_key: bytes = None, recipient_keypair: Keypair = None, sender_address: str = None, recipient_seed: str = None) -> str:
    """Decrypt message with recepient private key and sender puplic key

    :param encrypted_message: Message to decrypt
    :param sender_public_key: Sender public key
    :param recipient_keypair: Recepient account keypair

    :return: Decrypted message
    """
    if recipient_keypair is None:
        recipient_keypair = Account(recipient_seed, crypto_type=KeypairType.ED25519).keypair
    if sender_public_key is None:
        sender_public_key = Keypair(
            ss58_address=sender_address, crypto_type=KeypairType.ED25519
        ).public_key
    if encrypted_message[:2] == "0x":
        encrypted_message = encrypted_message[2:]
    bytes_encrypted = bytes.fromhex(encrypted_message)

    return recipient_keypair.decrypt_message(bytes_encrypted, sender_public_key)


async def create_notification(
    hass: HomeAssistant, service_data: tp.Dict[str, str]
) -> None:
    """Create HomeAssistant notification.

    :param hass: HomeAssistant instance
    :param service_data: Message for notification
    """
    service_data["notification_id"] = DOMAIN
    await hass.services.async_call(
        domain=NOTIFY_DOMAIN,
        service=SERVICE_PERSISTENT_NOTIFICATION,
        service_data=service_data,
    )


def to_thread(func: tp.Callable) -> tp.Coroutine:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


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
    sender_acc = Account(seed=sender_seed, crypto_type=KeypairType.ED25519)
    sender_kp = sender_acc.keypair
    receiver_kp = Keypair(
        ss58_address=receiver_address, crypto_type=KeypairType.ED25519
    )
    encrypted_data = encrypt_message(data, sender_kp, receiver_kp.public_key)
    picture_path = f"{dirname}/picture{number_of_picture}"
    with open(picture_path, "w") as f:
        f.write(encrypted_data)
    _LOGGER.debug(f"Created encrypted picture: {picture_path}")
    return picture_path


def create_temp_dir_and_copy_files(
    dirname: str,
    files: tp.List[str],
    sender_seed: tp.Optional[str] = None,
    receiver_address: tp.Optional[str] = None,
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
            dirpath += str(random.randint(1, 100))
        os.mkdir(dirpath)
        for filepath in files:
            filename = filepath.split("/")[-1]
            if sender_seed and receiver_address:
                with open(filepath, "r") as f:
                    data = f.read()
                sender_acc = Account(seed=sender_seed, crypto_type=KeypairType.ED25519)
                sender_kp = sender_acc.keypair
                receiver_kp = Keypair(
                    ss58_address=receiver_address, crypto_type=KeypairType.ED25519
                )
                encrypted_data = encrypt_message(
                    data, sender_kp, receiver_kp.public_key
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
