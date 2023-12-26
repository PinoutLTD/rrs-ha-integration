import websockets
import logging
import json

from homeassistant.core import HomeAssistant
from robonomicsinterface import Account
from substrateinterface import KeypairType

from .const import (
    LIBP2P_WS_SERVER,
    LIBP2P_LISTEN_PROTOCOL,
    LIBP2P_SEND_PROTOCOL,
    INTEGRATOR_PEER_ID,
    STORAGE_PINATA_CREDS,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET
)
from .utils import async_save_to_store, decrypt_message, encrypt_message

_LOGGER = logging.getLogger(__name__)


async def get_pinata_creds(
    hass: HomeAssistant, controller_seed: str, email: str, owner_address: str
):
    try:
        controller_address = Account(
            seed=controller_seed, crypto_type=KeypairType.ED25519
        ).get_address()
        async with websockets.connect(LIBP2P_WS_SERVER, ping_timeout=None) as websocket:
            _LOGGER.debug(f"Connected to WebSocket server at {LIBP2P_WS_SERVER}")
            await _subscribe_to_protocol(websocket, controller_address)
            encrypted_email = encrypt_message(email, sender_seed=controller_seed, recipient_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS)
            await _send_init_request(websocket, encrypted_email, controller_address, owner_address)
            while True:
                response = await websocket.recv()
                _LOGGER.debug(f"Received message from server: {response}")
                try:
                    json_resp = json.loads(response)
                except:
                    _LOGGER.debug(f"Got message is not json: {response}")
                    continue
                if "public" in json_resp and "private" in json_resp:
                    storage_data = {}
                    storage_data[CONF_PINATA_PUBLIC] = decrypt_message(
                        json_resp["public"],
                        sender_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
                        recipient_seed=controller_seed,
                    ).decode()
                    storage_data[CONF_PINATA_SECRET] = decrypt_message(
                        json_resp["private"],
                        sender_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
                        recipient_seed=controller_seed,
                    ).decode()
                    await async_save_to_store(
                        hass,
                        STORAGE_PINATA_CREDS,
                        storage_data,
                    )
    except websockets.exceptions.ConnectionClosedOK:
        _LOGGER.debug(f"Websockets connection closed")
    except Exception as e:
        _LOGGER.error(f"Websocket exception: {e}")


async def _subscribe_to_protocol(websocket, controller_address):
    msg_to_ws = json.dumps(
        {"protocols_to_listen": [f"{LIBP2P_LISTEN_PROTOCOL}/{controller_address}"]}
    )
    await _send_to_websocket(websocket, msg_to_ws)


async def _send_init_request(
    websocket, email: str, controller_address: str, owner_address: str
):
    data = {
        "email": email,
        "controller_address": controller_address,
        "owner_address": owner_address,
    }
    msg_to_ws = json.dumps(
        {
            "protocol": LIBP2P_SEND_PROTOCOL,
            "serverPeerId": INTEGRATOR_PEER_ID,
            "save_data": False,
            "data": data,
        }
    )
    await _send_to_websocket(websocket, msg_to_ws)


async def _send_to_websocket(websocket, msg: str):
    await websocket.send(msg)
    _LOGGER.debug(f"Sent to websocket: {msg}")
