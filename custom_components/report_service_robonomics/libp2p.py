import websockets
import logging
import json

from .const import (
    LIBP2P_WS_SERVER,
    LIBP2P_LISTEN_PROTOCOL,
    LIBP2P_SEND_PROTOCOL,
    INTEGRATOR_PEER_ID,
)

_LOGGER = logging.getLogger(__name__)


async def get_pinata_creds(address: str, email: str):
    try:
        async with websockets.connect(LIBP2P_WS_SERVER, ping_timeout=None) as websocket:
            _LOGGER.debug(f"Connected to WebSocket server at {LIBP2P_WS_SERVER}")
            await websocket.send(
                json.dumps(
                    {"protocols_to_listen": [f"{LIBP2P_LISTEN_PROTOCOL}/{address}"]}
                )
            )
            data = {"email": email, "address": address}
            msg_to_ws = json.dumps(
                {
                    "protocol": LIBP2P_SEND_PROTOCOL,
                    "serverPeerId": INTEGRATOR_PEER_ID,
                    "save_data": False,
                    "data": data,
                }
            )
            await websocket.send(msg_to_ws)
            while True:
                response = await websocket.recv()
                _LOGGER.debug(f"Received message from server: {response}")
                try:
                    json_resp = json.loads(response)
                except:
                    _LOGGER.debug(f"Got message is not json: {response}")
                    continue
                if "public" in json_resp and "private" in json_resp:
                    return json_resp
            # return {"public": "pub", "secret": "priv"}
    except websockets.exceptions.ConnectionClosedOK:
        _LOGGER.debug(f"Websockets connection closed")
    except Exception as e:
        _LOGGER.error(f"Websocket exception: {e}")
