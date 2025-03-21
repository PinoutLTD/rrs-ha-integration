import asyncio
import websockets
import typing as tp
import json
from .logger import logger
from .message import format_msg_from_libp2p, format_msg_for_subscribing, InitialMessage
from .decorators import set_websocket
from .protocols_manager import ProtocolsManager, CallbackTypes


class WebsocketClient:
    def __init__(
        self, protocols_manager: ProtocolsManager, proxy_server_url: str, peer_id_callback: tp.Optional[tp.Callable]
    ) -> None:
        self.websocket = None
        self.proxy_server_url: str = proxy_server_url
        self.is_listening = False
        self.is_connecting = False
        self.protocols_manager = protocols_manager
        self.peer_id_callback = peer_id_callback

    @set_websocket
    async def set_listener(self, reconnect: bool = False) -> None:
        logger.debug(f"Is listening: {self.is_listening}")
        if self.is_listening:
            return
        self.is_listening = True
        logger.debug(f"Connected to WebSocket server at {self.proxy_server_url}")
        loop = asyncio.get_event_loop()
        loop.create_task(self._consumer_handler(reconnect))

    async def send_msg(self, msg: str, reconnect: bool = False) -> None:
        await self._send_msg(msg, reconnect=reconnect)
        if not self.is_listening:
            logger.debug("Close connection after sending message")
            await self.close_connection()

    async def send_msg_to_subscribe(self, protocols: list) -> None:
        logger.debug(f"Subscribing to: {protocols}")
        msg = format_msg_for_subscribing(protocols)
        await self._send_msg(msg, reconnect=False)

    async def close_connection(self) -> None:
        await asyncio.sleep(0)
        logger.debug("Close websocket connection")
        if self.websocket is not None:
            await self.websocket.close()
            self.websocket = None
            logger.debug("Websocket connection closed")

    @set_websocket
    async def _send_msg(self, msg: str, reconnect: bool = False) -> None:
        await self.websocket.send(msg)

    async def _consumer_handler(self, reconnect: bool) -> None:
        try:
            while True:
                if self.websocket is not None:
                    message = await self.websocket.recv()
                    logger.debug(f"Received message from server: {message}")
                    await self._consumer(message)
                else:
                    self.is_listening = False
                    logger.debug("Stop listening websocket on None object")
                    return

        except websockets.exceptions.ConnectionClosedOK:
            self.is_listening = False
            logger.debug("Stop listening websocket on ConnectionClosedOK")

        except Exception as e:
            self.is_listening = False
            logger.error(f"Websocket exception: {e}")
            if reconnect:
                await asyncio.sleep(5)
                await self._reconnect(reconnect)

    async def _consumer(self, message: str) -> None:
        message = json.loads(message)
        if "peerId" in message:
            if self.peer_id_callback is not None:
                self.peer_id_callback(InitialMessage(message))
                return
        if message.get("protocol") in self.protocols_manager.protocols:
            protocol = message.get("protocol")
            formated_msg = format_msg_from_libp2p(message)
            callback_obj = self.protocols_manager.protocols[protocol]
            callback_type = callback_obj.callback_type
            if callback_type == CallbackTypes.AsyncType:
                await callback_obj.callback_function(formated_msg)
            else:
                callback_obj.callback_function(formated_msg)

    async def _reconnect(self, reconnect: bool) -> None:
        logger.debug("Reconnecting...")
        self.websocket = None
        await self.set_listener(reconnect=reconnect)
        while self.websocket is None:
            await asyncio.sleep(0.1)
            if not self.is_listening:
                return
        protocols = self.protocols_manager.get_protocols()
        logger.debug(f"Callbacks to resubscribe: {protocols}")
        await self.send_msg_to_subscribe(protocols)
