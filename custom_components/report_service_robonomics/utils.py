import asyncio
import functools
import logging
import os
import shutil
import tempfile
import typing as tp

from homeassistant.components.notify.const import DOMAIN as NOTIFY_DOMAIN
from homeassistant.components.notify.const import SERVICE_PERSISTENT_NOTIFICATION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from robonomicsinterface import Account
from substrateinterface import Keypair, KeypairType

_LOGGER = logging.getLogger(__name__)

VERSION_STORAGE = 6


def encrypt_message(message: tp.Union[bytes, str], sender_keypair: Keypair, recipient_public_key: bytes) -> str:
    """Encrypt message with sender private key and recipient public key

    :param message: Message to encrypt
    :param sender_keypair: Sender account Keypair
    :param recipient_public_key: Recipient public key

    :return: encrypted message
    """

    encrypted = sender_keypair.encrypt_message(message, recipient_public_key)
    return f"0x{encrypted.hex()}"


async def create_notification(hass: HomeAssistant, service_data: tp.Dict[str, str]) -> None:
    """Create HomeAssistant notification.

    :param hass: HomeAssistant instance
    :param service_data: Message for notification
    """

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
    return Store(hass, VERSION_STORAGE, _get_store_key(key), encoder=JSONEncoder, atomic_writes=True)


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
    receiver_kp = Keypair(ss58_address=receiver_address, crypto_type=KeypairType.ED25519)
    encrypted_data = encrypt_message(data, sender_kp, receiver_kp.public_key)
    picture_path = f"{dirname}/picture{number_of_picture}"
    with open(picture_path, "w") as f:
        f.write(encrypted_data)
    _LOGGER.debug(f"Created encrypted picture: {picture_path}")
    return picture_path


def write_data_to_temp_file(data: tp.Union[str, bytes], config: bool = False, filename: str = None) -> str:
    """
    Create file and store data in it

    :param data: data, which to be written to the file
    :param config: is file fo config (True) or for telemetry (False)
    :param filename: Name of the file if not config or z2m backup

    :return: path to created file
    """
    dirname = tempfile.gettempdir()
    if filename is not None:
        filepath = f"{dirname}/{filename}"
        if type(data) == str:
            with open(filepath, "w") as f:
                f.write(data)
        else:
            with open(filepath, "wb") as f:
                f.write(data)
    else:
        if type(data) == str:
            if config:
                filepath = f"{dirname}/config_encrypted-{time.time()}"
            else:
                filepath = f"{dirname}/data-{time.time()}"
            with open(filepath, "w") as f:
                f.write(data)
        else:
            filepath = f"{dirname}/z2m-backup.zip"
            with open(filepath, "wb") as f:
                f.write(data)
    return filepath


def create_temp_dir_and_copy_files(
    dirname: str, files: tp.List[str], sender_seed: tp.Optional[str] = None, receiver_address: tp.Optional[str] = None
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
                receiver_kp = Keypair(ss58_address=receiver_address, crypto_type=KeypairType.ED25519)
                encrypted_data = encrypt_message(data, sender_kp, receiver_kp.public_key)
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


def delete_temp_file(filename: str) -> None:
    """
    Delete temporary file

    :param filename: the name of the file to delete
    """
    os.remove(filename)
