import typing as tp
from .utils.websocket import WebsocketClient
from .utils.message import format_msg_to_libp2p
from .utils.protocols_manager import ProtocolsManager, Callback, CallbackTypes


class Libp2pProxyAPI:
    """A libp2p-proxy client object"""

    def __init__(self, proxy_server_url: str, peer_id_callback: tp.Optional[tp.Callable] = None) -> None:
        """
        :param proxy_server_url: URL to the proxy server to connect.
        :param peer_id_callback: Callback function for message with Libp2p peer id.
        """

        self.protocols_manager = ProtocolsManager()
        self.ws_client = WebsocketClient(self.protocols_manager, proxy_server_url, peer_id_callback)

    async def subscribe_to_protocol_sync(self, protocol: str, callback: tp.Callable, reconnect: bool = False) -> None:
        """Synchronously subscribes to a protocol to get messages.

        :param protocol: Protocol to subscribe.
        :param callback: Callback function for the messages from the protocol.
        :param reconnect: True if needs to reconnect to the proxy server in case of failure.
        """
        await self.ws_client.set_listener(reconnect=reconnect)
        callback_obj = Callback(callback, CallbackTypes.SyncType)
        self.protocols_manager.add_protocol(protocol, callback_obj)
        protocols = self.protocols_manager.get_protocols()
        await self.ws_client.send_msg_to_subscribe(protocols)

    async def subscribe_to_protocol_async(self, protocol: str, callback: tp.Callable, reconnect: bool = False) -> None:
        """Asynchronously subscribes to a protocol to get messages.

        :param protocol: Protocol to subscribe.
        :param callback: Callback function for the messages from the protocol.
        :param reconnect: True if needs to reconnect to the proxy server in case of failure.
        """

        await self.ws_client.set_listener(reconnect=reconnect)
        callback_obj = Callback(callback, CallbackTypes.AsyncType)
        self.protocols_manager.add_protocol(protocol, callback_obj)
        protocols = self.protocols_manager.get_protocols()
        await self.ws_client.send_msg_to_subscribe(protocols)

    async def send_msg_to_libp2p(
        self, data: str, protocol: str, server_peer_id: str = "", save_data: bool = False, reconnect: bool = False
    ) -> None:
        """ Sends a message to the proxy server.

        :param data: Data to send.
        :param protocol: Protocol to which the message should be sent.
        :param server_peer_id: Peer id of the specific node to which the message should be sent. 
        :param save_data: Either should the data be saved on the proxy server or not.
        :param reconnect: True if needs to reconnect to the proxy server in case of failure.
        """

        msg = format_msg_to_libp2p(data, protocol, server_peer_id, save_data)
        await self.ws_client.send_msg(msg, reconnect=reconnect)

    async def unsubscribe_from_protocol(self, protocol: str) -> None:
        """Unsubscribes from a protocol.

        :param protocol: Protocol to unsubscribe.
        """

        self.protocols_manager.remove_protocol(protocol)
        protocols = self.protocols_manager.get_protocols()
        await self.ws_client.send_msg_to_subscribe(protocols)
        if not protocols:
            await self.ws_client.close_connection()

    async def unsubscribe_from_all_protocols(self) -> None:
        """Unsubscribes from all protocols."""

        self.protocols_manager.remove_all_protocols()
        protocols = self.protocols_manager.get_protocols()
        await self.ws_client.send_msg_to_subscribe(protocols)
        await self.ws_client.close_connection()

    def is_connected(self) -> bool:
        """Checks if the connection is alive"""
        return self.ws_client.websocket is not None
